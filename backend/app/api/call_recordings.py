from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.db import get_db
from app.services.audit import record_audit_log
from app.services.recording_storage import (
    delete_local_file,
    delete_oss_object_if_exists,
    refresh_local_file_metadata,
    signed_oss_url,
    upload_to_oss_if_enabled,
)

router = APIRouter()


@router.get("", response_model=list[schemas.CallRecordingRead])
def list_call_recordings(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    query = db.query(models.CallRecording)
    if not current_user.is_admin:
        query = query.filter(models.CallRecording.user_id == current_user.id)
    if not include_deleted:
        query = query.filter(models.CallRecording.deleted_at.is_(None))

    recordings = query.order_by(models.CallRecording.id.desc()).limit(limit).all()
    record_audit_log(
        db,
        action="call_recording.list",
        resource_type="call_recording",
        user=current_user,
        request=request,
        after={"count": len(recordings), "include_deleted": include_deleted},
    )
    db.commit()
    return recordings


@router.get("/{recording_id:int}", response_model=schemas.CallRecordingRead)
def get_call_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    recording = _get_recording_or_404(db, recording_id, current_user)
    record_audit_log(
        db,
        action="call_recording.get",
        resource_type="call_recording",
        resource_id=recording.id,
        user=current_user,
        request=request,
    )
    db.commit()
    return recording


@router.get("/{recording_id:int}/play")
def play_call_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    recording = _get_recording_or_404(db, recording_id, current_user)
    response = _recording_response(recording, as_attachment=False)
    _audit_recording_access(db, request, current_user, recording, "call_recording.play")
    db.commit()
    return response


@router.get("/{recording_id:int}/download")
def download_call_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    recording = _get_recording_or_404(db, recording_id, current_user)
    response = _recording_response(recording, as_attachment=True)
    _audit_recording_access(db, request, current_user, recording, "call_recording.download")
    db.commit()
    return response


@router.delete("/{recording_id:int}", response_model=schemas.CallRecordingRead)
def delete_call_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    recording = _get_recording_or_404(db, recording_id, current_user)
    before = schemas.CallRecordingRead.model_validate(recording).model_dump(mode="json")
    _delete_recording_payload(recording, current_user)
    db.flush()
    record_audit_log(
        db,
        action="call_recording.delete",
        resource_type="call_recording",
        resource_id=recording.id,
        user=current_user,
        request=request,
        before=before,
        after=schemas.CallRecordingRead.model_validate(recording).model_dump(mode="json"),
    )
    db.commit()
    db.refresh(recording)
    return recording


@router.post("/retention/purge", response_model=list[schemas.CallRecordingRead])
def purge_expired_call_recordings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required")

    now = datetime.now(UTC)
    expired = (
        db.query(models.CallRecording)
        .filter(
            models.CallRecording.deleted_at.is_(None),
            models.CallRecording.retention_expires_at.is_not(None),
            models.CallRecording.retention_expires_at <= now,
        )
        .order_by(models.CallRecording.id)
        .limit(500)
        .all()
    )
    for recording in expired:
        _delete_recording_payload(recording, current_user, status_value="expired")

    record_audit_log(
        db,
        action="call_recording.purge_expired",
        resource_type="call_recording",
        user=current_user,
        request=request,
        after={"count": len(expired)},
    )
    db.commit()
    return expired


def _get_recording_or_404(db: Session, recording_id: int, current_user: models.AppUser) -> models.CallRecording:
    query = db.query(models.CallRecording).filter(models.CallRecording.id == recording_id)
    if not current_user.is_admin:
        query = query.filter(models.CallRecording.user_id == current_user.id)
    recording = query.first()
    if recording is None:
        raise HTTPException(status_code=404, detail="Call recording not found")
    if recording.deleted_at:
        raise HTTPException(status_code=410, detail="Call recording has been deleted")
    return recording


def _recording_response(recording: models.CallRecording, *, as_attachment: bool):
    refresh_local_file_metadata(recording)
    if recording.status != "available":
        raise HTTPException(status_code=409, detail="Recording is not available yet")
    if recording.oss_key and recording.storage_backend == "oss":
        return RedirectResponse(signed_oss_url(recording, as_attachment=as_attachment))

    if not recording.local_path:
        raise HTTPException(status_code=404, detail="Recording file path is missing")

    path = Path(recording.local_path)
    if not path.exists() or not path.is_file():
        if recording.status == "available":
            try:
                upload_to_oss_if_enabled(recording)
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="Recording file is not available")

    return FileResponse(
        path,
        media_type=recording.content_type or "audio/wav",
        filename=recording.filename if as_attachment else None,
    )


def _delete_recording_payload(
    recording: models.CallRecording,
    current_user: models.AppUser,
    status_value: str = "deleted",
) -> None:
    try:
        delete_local_file(recording)
    except OSError as exc:
        recording.failure_reason = f"Local delete failed: {exc}"
    try:
        delete_oss_object_if_exists(recording)
    except Exception as exc:
        recording.failure_reason = f"OSS delete failed: {exc}"
    recording.status = status_value
    recording.deleted_at = datetime.now(UTC)
    recording.deleted_by_user_id = current_user.id


def _audit_recording_access(
    db: Session,
    request: Request,
    current_user: models.AppUser,
    recording: models.CallRecording,
    action: str,
) -> None:
    record_audit_log(
        db,
        action=action,
        resource_type="call_recording",
        resource_id=recording.id,
        user=current_user,
        request=request,
        after=schemas.CallRecordingRead.model_validate(recording).model_dump(mode="json"),
    )
