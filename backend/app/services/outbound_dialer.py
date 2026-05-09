import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.services.asterisk import AmiError, AsteriskAmiClient
from app.services.outbound_routing import candidate_trunks, mark_trunk_attempt
from app.services.recording_storage import (
    asterisk_recording_path,
    build_recording_filename,
    ensure_recording_dir,
    local_recording_path,
    retention_expires_at,
)

logger = logging.getLogger(__name__)


class OutboundDialError(RuntimeError):
    pass


def originate_with_failover(
    db: Session,
    call: models.OutboundCall,
    *,
    preferred_trunk: models.SipTrunk,
    destination: str,
    caller_id: str | None = None,
) -> models.SipTrunk:
    attempted_endpoint_names = attempted_endpoint_names_from_call(db, call)
    candidates = candidate_trunks(
        db,
        preferred_trunk=preferred_trunk,
        exclude_ids=attempted_ids_from_call(call),
        current_call_id=call.id,
    )
    if not candidates:
        raise OutboundDialError("当前没有可用 SIP 线路，或线路已达到最大并发")

    errors: list[str] = []
    skipped_duplicate_endpoint = False
    for trunk in candidates:
        endpoint_name = endpoint_for_trunk(trunk)
        if endpoint_name in attempted_endpoint_names:
            skipped_duplicate_endpoint = True
            continue
        attempted_endpoint_names.add(endpoint_name)
        try:
            originate_on_trunk(db, call, trunk=trunk, destination=destination, caller_id=caller_id, endpoint_name=endpoint_name)
            return trunk
        except AmiError as exc:
            message = f"{trunk.name}: {exc}"
            errors.append(message)
            trunk.status = "error"
            trunk.last_health_checked_at = datetime.now(UTC)
            trunk.last_health_message = str(exc)[:500]
            logger.warning("Outbound call %s failed on trunk %s: %s", call.id, trunk.name, exc)

    if skipped_duplicate_endpoint and not errors:
        raise OutboundDialError("没有其它未尝试的 Asterisk 外呼出口可重试；系统已避免重复拨打同一个真实 SIP 出口")
    raise OutboundDialError("所有可用 SIP 线路外呼失败：" + "；".join(errors))


def retry_call_after_originate_failure(
    db: Session,
    call: models.OutboundCall,
    *,
    reason: str,
) -> bool:
    if call.answered_at or call.status not in {"queued", "initiating", "dialing", "ringing", "hangup_requested"}:
        return False
    current_trunk = call.sip_trunk
    if current_trunk is None:
        return False
    _mark_recordings_failed(db, call, reason)
    originate_with_failover(
        db,
        call,
        preferred_trunk=current_trunk,
        destination=call.destination_number,
        caller_id=call.caller_id,
    )
    return True


def originate_on_trunk(
    db: Session,
    call: models.OutboundCall,
    *,
    trunk: models.SipTrunk,
    destination: str,
    caller_id: str | None = None,
    endpoint_name: str | None = None,
) -> None:
    db.flush()
    action_id = f"manual-{call.id}-{uuid.uuid4().hex}"
    channel_id = f"outbound-{call.id}-{uuid.uuid4().hex}"
    effective_caller_id = caller_id or trunk.caller_id or settings.app_name

    call.sip_trunk_id = trunk.id
    call.caller_id = effective_caller_id
    call.ami_action_id = action_id
    call.ami_channel_id = channel_id
    call.status = "initiating"
    mark_trunk_attempt(call, trunk)
    db.flush()
    db.commit()
    db.refresh(call)

    ami_client = AsteriskAmiClient()
    endpoint_name = endpoint_name or endpoint_for_trunk(trunk)
    _ensure_asterisk_endpoint(ami_client, endpoint_name)
    ami_client.originate(
        trunk_name=endpoint_name,
        destination=destination,
        caller_id=effective_caller_id,
        action_id=action_id,
        channel_id=channel_id,
    )

    now = datetime.now(UTC)
    db.refresh(call)
    if call.status not in {"completed", "hangup", "failed", "blocked", "rate_limited"}:
        call.status = "dialing"
        call.started_at = call.started_at or now
        call.failure_reason = None
        recording = _create_pending_recording(db, call)
        try_start_recording(call, recording, ami_client)
    logger.info("Outbound call %s originated on DB trunk %s through Asterisk endpoint %s", call.id, trunk.name, endpoint_name)


def endpoint_for_trunk(trunk: models.SipTrunk) -> str:
    return settings.asterisk_outbound_endpoint.strip() or trunk.name


def attempted_endpoint_names_from_call(db: Session, call: models.OutboundCall) -> set[str]:
    attempted_trunk_ids = attempted_ids_from_call(call)
    if not attempted_trunk_ids:
        return set()
    if settings.asterisk_outbound_endpoint.strip():
        return {settings.asterisk_outbound_endpoint.strip()}
    trunks = db.query(models.SipTrunk).filter(models.SipTrunk.id.in_(attempted_trunk_ids)).all()
    return {endpoint_for_trunk(trunk) for trunk in trunks}


def _ensure_asterisk_endpoint(ami_client: AsteriskAmiClient, endpoint_name: str) -> None:
    output = ami_client.command(f"pjsip show endpoint {endpoint_name}")
    lowered = output.lower()
    if "unable to find" in lowered or "not found" in lowered:
        raise AmiError(f"Asterisk 未加载外呼 endpoint {endpoint_name}，请检查 pjsip.conf 并重启 asterisk 容器")


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
        file_path=local_recording_path(filename),
        asterisk_path=asterisk_recording_path(filename),
        retention_expires_at=retention_expires_at(),
    )
    db.add(recording)
    db.flush()
    return recording


def try_start_recording(
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


def start_pending_recordings_on_channel(
    db: Session,
    call: models.OutboundCall,
    *,
    channel: str,
    ami_client: AsteriskAmiClient | None = None,
) -> None:
    ami_client = ami_client or AsteriskAmiClient()
    call.asterisk_channel = channel
    recordings = (
        db.query(models.CallRecording)
        .filter(
            models.CallRecording.outbound_call_id == call.id,
            models.CallRecording.deleted_at.is_(None),
            models.CallRecording.status.in_(["pending", "failed"]),
        )
        .order_by(models.CallRecording.id.desc())
        .all()
    )
    for recording in recordings:
        ami_client.start_mixmonitor(channel, recording.asterisk_path or recording.local_path or recording.filename)
        recording.status = "recording"
        recording.failure_reason = None


def _mark_recordings_failed(db: Session, call: models.OutboundCall, reason: str) -> None:
    recordings = (
        db.query(models.CallRecording)
        .filter(
            models.CallRecording.outbound_call_id == call.id,
            models.CallRecording.status.in_(["pending", "recording"]),
        )
        .all()
    )
    for recording in recordings:
        recording.status = "failed"
        recording.failure_reason = reason[:500]


def attempted_ids_from_call(call: models.OutboundCall) -> set[int]:
    if not call.attempted_trunk_ids:
        return set()
    return {int(item) for item in call.attempted_trunk_ids.split(",") if item.strip().isdigit()}
