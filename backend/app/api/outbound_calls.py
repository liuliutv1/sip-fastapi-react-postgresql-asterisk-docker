import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.services.asterisk import AmiError, AsteriskAmiClient
from app.services.audit import record_audit_log
from app.services.recording_storage import (
    asterisk_recording_path,
    build_recording_filename,
    ensure_recording_dir,
    local_recording_path,
    refresh_local_file_metadata,
    retention_expires_at,
    upload_to_oss_if_enabled,
)

router = APIRouter()

ACTIVE_STATUSES = {"initiating", "dialing", "ringing", "in_progress", "hangup_requested"}
TERMINAL_STATUSES = {"ended", "failed", "blocked", "rate_limited"}


@router.get("", response_model=list[schemas.OutboundCallRead])
def list_outbound_calls(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    query = db.query(models.OutboundCall)
    if not current_user.is_admin:
        query = query.filter(models.OutboundCall.user_id == current_user.id)
    return query.order_by(models.OutboundCall.id.desc()).limit(min(max(limit, 1), 500)).all()


@router.post("", response_model=schemas.OutboundCallRead, status_code=status.HTTP_201_CREATED)
def originate_manual_call(
    payload: schemas.OutboundCallCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    trunk = (
        db.query(models.SipTrunk)
        .filter(models.SipTrunk.id == payload.sip_trunk_id, models.SipTrunk.enabled.is_(True))
        .first()
    )
    if trunk is None:
        raise HTTPException(status_code=404, detail="Enabled SIP trunk not found")

    blocked_entry = (
        db.query(models.PhoneBlacklist)
        .filter(
            models.PhoneBlacklist.normalized_number == payload.destination_number,
            models.PhoneBlacklist.enabled.is_(True),
        )
        .first()
    )
    if blocked_entry:
        call = _create_call(
            db,
            current_user=current_user,
            payload=payload,
            status_value="blocked",
            failure_reason="Destination number is blacklisted",
        )
        _audit_call(db, request, current_user, "outbound_call.blocked", call)
        db.commit()
        raise HTTPException(status_code=403, detail="Destination number is blacklisted")

    if _is_rate_limited(db, current_user):
        call = _create_call(
            db,
            current_user=current_user,
            payload=payload,
            status_value="rate_limited",
            failure_reason="Manual outbound call rate limit exceeded",
        )
        _audit_call(db, request, current_user, "outbound_call.rate_limited", call)
        db.commit()
        raise HTTPException(status_code=429, detail="Manual outbound call rate limit exceeded")

    call = _create_call(db, current_user=current_user, payload=payload, status_value="initiating")
    db.flush()
    action_id = f"manual-{call.id}-{uuid.uuid4().hex}"
    channel_id = f"outbound-{call.id}-{uuid.uuid4().hex}"
    call.ami_action_id = action_id
    call.ami_channel_id = channel_id

    caller_id = payload.caller_id or trunk.caller_id or settings.app_name
    call.caller_id = caller_id
    try:
        ami_client = AsteriskAmiClient()
        ami_client.originate(
            trunk_name=trunk.name,
            destination=payload.destination_number,
            caller_id=caller_id,
            action_id=action_id,
            channel_id=channel_id,
        )
        now = datetime.now(UTC)
        call.status = "dialing"
        call.started_at = now
        call.failure_reason = None
        recording = _create_pending_recording(db, call)
        _try_start_recording(call, recording, ami_client)
    except AmiError as exc:
        call.status = "failed"
        call.failure_reason = str(exc)
        call.ended_at = datetime.now(UTC)

    db.flush()
    _audit_call(db, request, current_user, "outbound_call.originate", call)
    db.commit()
    db.refresh(call)
    return call


@router.post("/{call_id}/refresh", response_model=schemas.OutboundCallRead)
def refresh_outbound_call_status(
    call_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    call = _get_call_or_404(db, call_id, current_user)
    if call.status in TERMINAL_STATUSES or not call.ami_channel_id:
        return call

    before = schemas.OutboundCallRead.model_validate(call).model_dump(mode="json")
    try:
        ami_client = AsteriskAmiClient()
        _sync_call_status(call, ami_client)
        _sync_recordings(db, call, ami_client)
    except AmiError as exc:
        call.failure_reason = str(exc)
    db.flush()
    record_audit_log(
        db,
        action="outbound_call.refresh",
        resource_type="outbound_call",
        resource_id=call.id,
        user=current_user,
        request=request,
        before=before,
        after=schemas.OutboundCallRead.model_validate(call).model_dump(mode="json"),
    )
    db.commit()
    db.refresh(call)
    return call


@router.post("/{call_id}/hangup", response_model=schemas.OutboundCallRead)
def hangup_outbound_call(
    call_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    call = _get_call_or_404(db, call_id, current_user)
    before = schemas.OutboundCallRead.model_validate(call).model_dump(mode="json")
    if call.status in TERMINAL_STATUSES:
        return call

    if not call.ami_channel_id:
        call.status = "ended"
        call.ended_at = datetime.now(UTC)
    else:
        try:
            ami_client = AsteriskAmiClient()
            channel = ami_client.find_channel_by_id(call.ami_channel_id)
            if channel and channel.channel:
                for recording in _call_recordings(db, call):
                    if recording.status == "recording":
                        try:
                            ami_client.stop_mixmonitor(channel.channel)
                        except AmiError:
                            pass
                ami_client.hangup(channel.channel)
                call.asterisk_channel = channel.channel
                call.status = "hangup_requested"
            else:
                call.status = "ended"
                call.ended_at = datetime.now(UTC)
        except AmiError as exc:
            call.failure_reason = str(exc)
            db.flush()
            record_audit_log(
                db,
                action="outbound_call.hangup_failed",
                resource_type="outbound_call",
                resource_id=call.id,
                user=current_user,
                request=request,
                before=before,
                after=schemas.OutboundCallRead.model_validate(call).model_dump(mode="json"),
            )
            db.commit()
            raise HTTPException(status_code=502, detail="Asterisk AMI hangup failed") from exc

    db.flush()
    record_audit_log(
        db,
        action="outbound_call.hangup",
        resource_type="outbound_call",
        resource_id=call.id,
        user=current_user,
        request=request,
        before=before,
        after=schemas.OutboundCallRead.model_validate(call).model_dump(mode="json"),
    )
    db.commit()
    db.refresh(call)
    return call


def _create_call(
    db: Session,
    *,
    current_user: models.AppUser,
    payload: schemas.OutboundCallCreate,
    status_value: str,
    failure_reason: str | None = None,
) -> models.OutboundCall:
    call = models.OutboundCall(
        user_id=current_user.id,
        sip_trunk_id=payload.sip_trunk_id,
        destination_number=payload.destination_number,
        caller_id=payload.caller_id,
        status=status_value,
        failure_reason=failure_reason,
    )
    db.add(call)
    db.flush()
    return call


def _is_rate_limited(db: Session, current_user: models.AppUser) -> bool:
    window_start = datetime.now(UTC) - timedelta(seconds=settings.manual_outbound_rate_limit_window_seconds)
    count = (
        db.query(func.count(models.OutboundCall.id))
        .filter(
            models.OutboundCall.user_id == current_user.id,
            models.OutboundCall.created_at >= window_start,
            models.OutboundCall.status.notin_(["blocked", "rate_limited"]),
        )
        .scalar()
    )
    return int(count or 0) >= settings.manual_outbound_rate_limit_count


def _get_call_or_404(db: Session, call_id: int, current_user: models.AppUser) -> models.OutboundCall:
    query = db.query(models.OutboundCall).filter(models.OutboundCall.id == call_id)
    if not current_user.is_admin:
        query = query.filter(models.OutboundCall.user_id == current_user.id)
    call = query.first()
    if call is None:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    return call


def _sync_call_status(call: models.OutboundCall, ami_client: AsteriskAmiClient) -> None:
    channel = ami_client.find_channel_by_id(call.ami_channel_id or "")
    if channel is None:
        if call.status in ACTIVE_STATUSES:
            call.status = "ended"
            call.ended_at = call.ended_at or datetime.now(UTC)
        return

    call.asterisk_channel = channel.channel
    state = (channel.state or "").lower()
    if state == "up":
        call.status = "in_progress"
        call.answered_at = call.answered_at or datetime.now(UTC)
    elif "ring" in state:
        call.status = "ringing"
    else:
        call.status = "dialing"


def _create_pending_recording(db: Session, call: models.OutboundCall) -> models.CallRecording:
    ensure_recording_dir()
    filename = build_recording_filename(call.id)
    recording = models.CallRecording(
        outbound_call_id=call.id,
        user_id=call.user_id,
        destination_number=call.destination_number,
        status="pending",
        storage_backend="local",
        filename=filename,
        content_type="audio/wav",
        local_path=local_recording_path(filename),
        asterisk_path=asterisk_recording_path(filename),
        retention_expires_at=retention_expires_at(),
    )
    db.add(recording)
    db.flush()
    return recording


def _try_start_recording(
    call: models.OutboundCall,
    recording: models.CallRecording,
    ami_client: AsteriskAmiClient,
) -> None:
    if not call.ami_channel_id or recording.status not in {"pending", "failed"}:
        return
    channel = ami_client.find_channel_by_id(call.ami_channel_id)
    if channel is None or not channel.channel:
        return
    ami_client.start_mixmonitor(channel.channel, recording.asterisk_path or recording.local_path or recording.filename)
    call.asterisk_channel = channel.channel
    recording.status = "recording"
    recording.failure_reason = None


def _sync_recordings(db: Session, call: models.OutboundCall, ami_client: AsteriskAmiClient) -> None:
    recordings = _call_recordings(db, call)
    for recording in recordings:
        if recording.deleted_at:
            continue
        if recording.status == "pending":
            try:
                _try_start_recording(call, recording, ami_client)
            except AmiError as exc:
                recording.status = "failed"
                recording.failure_reason = str(exc)
        if call.status in TERMINAL_STATUSES or call.status == "ended":
            _finalize_recording(recording)
        elif recording.status == "recording":
            refresh_local_file_metadata(recording, mark_available=False)


def _finalize_recording(recording: models.CallRecording) -> None:
    refresh_local_file_metadata(recording)
    if recording.status == "available":
        try:
            upload_to_oss_if_enabled(recording)
        except Exception as exc:
            recording.failure_reason = f"OSS upload failed: {exc}"
    elif recording.status in {"pending", "recording"}:
        recording.status = "failed"
        recording.failure_reason = recording.failure_reason or "Recording file was not found"


def _call_recordings(db: Session, call: models.OutboundCall) -> list[models.CallRecording]:
    return (
        db.query(models.CallRecording)
        .filter(models.CallRecording.outbound_call_id == call.id)
        .order_by(models.CallRecording.id.desc())
        .all()
    )


def _audit_call(
    db: Session,
    request: Request,
    current_user: models.AppUser,
    action: str,
    call: models.OutboundCall,
) -> None:
    record_audit_log(
        db,
        action=action,
        resource_type="outbound_call",
        resource_id=call.id,
        user=current_user,
        request=request,
        after=schemas.OutboundCallRead.model_validate(call).model_dump(mode="json"),
    )
