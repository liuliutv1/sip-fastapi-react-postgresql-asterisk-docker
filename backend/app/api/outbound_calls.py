from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.services.asterisk import AmiError, AsteriskAmiClient
from app.services.audit import record_audit_log
from app.services.call_lifecycle import (
    ACTIVE_CALL_STATUSES,
    TERMINAL_CALL_STATUSES,
    call_recordings,
    complete_call_from_hangup,
    finalize_recording,
    find_active_call_by_destination,
)
from app.services.outbound_dialer import OutboundDialError, originate_with_failover, try_start_recording
from app.services.recording_storage import refresh_local_file_metadata

router = APIRouter()

ACTIVE_STATUSES = ACTIVE_CALL_STATUSES
TERMINAL_STATUSES = TERMINAL_CALL_STATUSES
DUPLICATE_CALL_MESSAGE = "该号码当前已有进行中的呼叫，请等待结束后再发起外呼"


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
    _expire_stale_active_calls(db)

    trunk = (
        db.query(models.SipTrunk)
        .filter(models.SipTrunk.id == payload.sip_trunk_id, models.SipTrunk.enabled.is_(True))
        .first()
    )
    if trunk is None:
        raise HTTPException(status_code=404, detail="Enabled SIP trunk not found")

    active_call = find_active_call_by_destination(db, payload.destination_number)
    if active_call:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DUPLICATE_CALL_MESSAGE)

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

    try:
        call = _create_call(db, current_user=current_user, payload=payload, status_value="initiating")
        db.commit()
        db.refresh(call)
    except IntegrityError as exc:
        db.rollback()
        if "uq_outbound_calls_active_destination" in str(exc.orig):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DUPLICATE_CALL_MESSAGE) from exc
        raise
    try:
        originate_with_failover(
            db,
            call,
            preferred_trunk=trunk,
            destination=payload.destination_number,
            caller_id=payload.caller_id,
        )
    except OutboundDialError as exc:
        call.status = "failed"
        call.failure_reason = str(exc)
        call.ended_at = datetime.now(UTC)

    db.flush()
    db.commit()
    db.refresh(call)
    _safe_audit_call(db, request, current_user, "outbound_call.originate", call)
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
        if call.status in {"completed", "hangup", "ended"}:
            _sync_recordings(db, call, None)
            db.commit()
        return call

    before = schemas.OutboundCallRead.model_validate(call).model_dump(mode="json")
    try:
        ami_client = AsteriskAmiClient()
        _sync_call_status(db, call, ami_client)
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
        _sync_recordings(db, call, None)
        db.commit()
        return call

    if not call.ami_channel_id:
        complete_call_from_hangup(db, call, status_value="completed", reason="用户手动挂断")
    else:
        try:
            ami_client = AsteriskAmiClient()
            channel = ami_client.find_channel_by_id(call.ami_channel_id)
            if channel and channel.channel:
                for recording in call_recordings(db, call):
                    if recording.status == "recording":
                        try:
                            ami_client.stop_mixmonitor(channel.channel)
                        except AmiError:
                            pass
                ami_client.hangup(channel.channel)
                call.asterisk_channel = channel.channel
                call.status = "hangup_requested"
            else:
                complete_call_from_hangup(db, call, status_value="completed", reason="通道已结束")
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


def _expire_stale_active_calls(db: Session) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=max(settings.stale_outbound_call_timeout_minutes, 1))
    stale_calls = (
        db.query(models.OutboundCall)
        .filter(
            models.OutboundCall.status.in_(ACTIVE_STATUSES),
            models.OutboundCall.created_at < cutoff,
            models.OutboundCall.answered_at.is_(None),
        )
        .limit(200)
        .all()
    )
    for call in stale_calls:
        call.status = "failed"
        call.failure_reason = call.failure_reason or "呼叫超过等待时间，系统已自动结束，避免占用线路"
        call.ended_at = call.ended_at or datetime.now(UTC)
        for recording in call_recordings(db, call):
            if recording.status in {"pending", "recording"}:
                recording.status = "failed"
                recording.failure_reason = recording.failure_reason or "呼叫未接通，未生成有效录音"
    if stale_calls:
        db.flush()


def _get_call_or_404(db: Session, call_id: int, current_user: models.AppUser) -> models.OutboundCall:
    query = db.query(models.OutboundCall).filter(models.OutboundCall.id == call_id)
    if not current_user.is_admin:
        query = query.filter(models.OutboundCall.user_id == current_user.id)
    call = query.first()
    if call is None:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    return call


def _sync_call_status(db: Session, call: models.OutboundCall, ami_client: AsteriskAmiClient) -> None:
    channel = ami_client.find_channel_by_id(call.ami_channel_id or "")
    if channel is None:
        if call.status in ACTIVE_STATUSES:
            complete_call_from_hangup(db, call, status_value="completed", reason="Asterisk 通道已结束")
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


def _sync_recordings(db: Session, call: models.OutboundCall, ami_client: AsteriskAmiClient | None) -> None:
    recordings = call_recordings(db, call)
    for recording in recordings:
        if recording.deleted_at:
            continue
        if recording.status == "pending" and ami_client is not None:
            try:
                try_start_recording(call, recording, ami_client)
            except AmiError as exc:
                recording.status = "failed"
                recording.failure_reason = str(exc)
        if call.status in TERMINAL_STATUSES or call.status == "ended":
            finalize_recording(recording)
        elif recording.status == "recording":
            refresh_local_file_metadata(recording, mark_available=False)


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


def _safe_audit_call(
    db: Session,
    request: Request,
    current_user: models.AppUser,
    action: str,
    call: models.OutboundCall,
) -> None:
    try:
        _audit_call(db, request, current_user, action, call)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
