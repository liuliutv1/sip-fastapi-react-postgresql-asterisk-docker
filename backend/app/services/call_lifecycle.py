import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.services.audit import record_audit_log
from app.services.recording_storage import refresh_local_file_metadata, upload_to_oss_if_enabled

ACTIVE_CALL_STATUSES = {"queued", "initiating", "dialing", "ringing", "answered", "in_progress", "hangup_requested"}
TERMINAL_CALL_STATUSES = {"ended", "completed", "hangup", "failed", "blocked", "rate_limited"}


def find_active_call_by_destination(db: Session, destination_number: str) -> models.OutboundCall | None:
    return (
        db.query(models.OutboundCall)
        .filter(
            models.OutboundCall.destination_number == destination_number,
            models.OutboundCall.status.in_(ACTIVE_CALL_STATUSES),
        )
        .order_by(models.OutboundCall.id.desc())
        .first()
    )


def complete_call_from_hangup(
    db: Session,
    call: models.OutboundCall,
    *,
    status_value: str = "completed",
    reason: str | None = None,
    channel: str | None = None,
    ended_at: datetime | None = None,
) -> None:
    if channel:
        call.asterisk_channel = channel
    if reason:
        call.hangup_cause = reason[:120]
    if call.status in ACTIVE_CALL_STATUSES:
        call.status = status_value
    call.ended_at = call.ended_at or ended_at or datetime.now(UTC)

    for recording in call_recordings(db, call):
        before_status = recording.status
        finalize_recording(recording)
        if before_status != "completed" and recording.status == "completed":
            record_audit_log(
                db,
                action="call_recording.completed",
                resource_type="call_recording",
                resource_id=recording.id,
                after={
                    "filename": recording.filename,
                    "file_path": recording.file_path,
                    "storage_backend": recording.storage_backend,
                    "outbound_call_id": recording.outbound_call_id,
                },
            )


def finalize_recording(recording: models.CallRecording, *, wait_seconds: float = 3.0) -> None:
    if recording.deleted_at or recording.status in {"completed", "deleted", "expired"}:
        return

    deadline = time.monotonic() + wait_seconds
    while True:
        refresh_local_file_metadata(recording)
        if recording.status == "completed":
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.35)

    if recording.status == "completed":
        try:
            upload_to_oss_if_enabled(recording)
        except Exception as exc:
            recording.failure_reason = f"OSS upload failed: {exc}"
            if settings.recordings_storage_backend.lower() == "oss":
                recording.status = "failed"
        return

    if recording.status in {"pending", "recording"}:
        recording.status = "failed"
        recording.failure_reason = recording.failure_reason or "录音文件未生成或尚未写入完成"


def call_recordings(db: Session, call: models.OutboundCall) -> list[models.CallRecording]:
    return (
        db.query(models.CallRecording)
        .filter(models.CallRecording.outbound_call_id == call.id)
        .order_by(models.CallRecording.id.desc())
        .all()
    )
