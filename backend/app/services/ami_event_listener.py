import logging
import re
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.db import SessionLocal
from app.services.asterisk import AsteriskAmiClient
from app.services.audit import record_audit_log
from app.services.call_lifecycle import ACTIVE_CALL_STATUSES, TERMINAL_CALL_STATUSES, complete_call_from_hangup
from app.services.outbound_dialer import OutboundDialError, retry_call_after_originate_failure, start_pending_recordings_on_channel
from app.services.phone_numbers import mask_phone_number

logger = logging.getLogger(__name__)

PJSIP_DESTINATION_RE = re.compile(r"^PJSIP/(?P<number>[^@/-]+)@")


class AmiHangupEventListener:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.asterisk_ami_event_listener_enabled:
            logger.info("Asterisk AMI Hangup event listener is disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ami-hangup-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                logger.info("Connecting to Asterisk AMI event stream")
                client = AsteriskAmiClient(timeout=10.0)
                for event in client.iter_events({"Hangup", "OriginateResponse"}):
                    if self._stop_event.is_set():
                        break
                    event_name = event.get("Event")
                    if event_name == "Hangup":
                        self._handle_hangup_event(event)
                    elif event_name == "OriginateResponse":
                        self._handle_originate_response_event(event)
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning("Asterisk AMI event stream interrupted: %s", exc)
                    self._stop_event.wait(5)

    def _handle_hangup_event(self, event: dict[str, str]) -> None:
        channel = event.get("Channel")
        unique_id = event.get("Uniqueid")
        linked_id = event.get("Linkedid")
        reason = _hangup_reason(event)

        with SessionLocal() as db:
            call = self._find_call(db, channel=channel, unique_id=unique_id, linked_id=linked_id)
            if call is None:
                logger.debug("Hangup event did not match an outbound call: %s", _safe_event_summary(event))
                return

            before = _call_snapshot(call)
            if call.status in TERMINAL_CALL_STATUSES:
                complete_call_from_hangup(db, call, reason=reason, channel=channel, ended_at=datetime.now(UTC))
            else:
                complete_call_from_hangup(db, call, status_value="completed", reason=reason, channel=channel, ended_at=datetime.now(UTC))

            db.flush()
            record_audit_log(
                db,
                action="outbound_call.hangup_event",
                resource_type="outbound_call",
                resource_id=call.id,
                before=before,
                after=_call_snapshot(call),
            )
            db.commit()
            logger.info("Outbound call %s completed from AMI Hangup event", call.id)

    def _handle_originate_response_event(self, event: dict[str, str]) -> None:
        if (event.get("Response") or "").lower() == "success":
            self._handle_originate_success_event(event)
            return

        action_id = event.get("ActionID")
        reason = _originate_failure_reason(event)
        if not action_id:
            return

        with SessionLocal() as db:
            call = (
                db.query(models.OutboundCall)
                .filter(models.OutboundCall.ami_action_id == action_id)
                .order_by(models.OutboundCall.id.desc())
                .first()
            )
            if call is None or call.status in TERMINAL_CALL_STATUSES:
                return

            before = _call_snapshot(call)
            if _is_retryable_originate_failure(reason):
                try:
                    if retry_call_after_originate_failure(db, call, reason=reason):
                        db.flush()
                        record_audit_log(
                            db,
                            action="outbound_call.retry_next_trunk",
                            resource_type="outbound_call",
                            resource_id=call.id,
                            before=before,
                            after=_call_snapshot(call),
                        )
                        db.commit()
                        logger.warning("Outbound call %s retried on next trunk after failure: %s", call.id, reason)
                        return
                except OutboundDialError as exc:
                    reason = f"{reason}; retry failed: {exc}"

            call.failure_reason = reason[:500]
            complete_call_from_hangup(db, call, status_value="failed", reason=reason, ended_at=datetime.now(UTC))
            db.flush()
            record_audit_log(
                db,
                action="outbound_call.originate_failed",
                resource_type="outbound_call",
                resource_id=call.id,
                before=before,
                after=_call_snapshot(call),
            )
            db.commit()
            logger.error("Outbound call %s failed: %s", call.id, reason)

    def _handle_originate_success_event(self, event: dict[str, str]) -> None:
        action_id = event.get("ActionID")
        if not action_id:
            return

        with SessionLocal() as db:
            call = (
                db.query(models.OutboundCall)
                .filter(models.OutboundCall.ami_action_id == action_id)
                .order_by(models.OutboundCall.id.desc())
                .first()
            )
            if call is None or call.status in TERMINAL_CALL_STATUSES:
                return

            before = _call_snapshot(call)
            now = datetime.now(UTC)
            channel = event.get("Channel") or call.asterisk_channel
            call.status = "in_progress"
            call.answered_at = call.answered_at or now
            if channel:
                call.asterisk_channel = channel
                try:
                    start_pending_recordings_on_channel(db, call, channel=channel)
                except Exception as exc:
                    logger.warning("Failed to start recording for call %s on channel %s: %s", call.id, _mask_channel_destination(channel), exc)
            db.flush()
            record_audit_log(
                db,
                action="outbound_call.answered",
                resource_type="outbound_call",
                resource_id=call.id,
                before=before,
                after=_call_snapshot(call),
            )
            db.commit()

    def _find_call(
        self,
        db: Session,
        *,
        channel: str | None,
        unique_id: str | None,
        linked_id: str | None,
    ) -> models.OutboundCall | None:
        channel_ids = [value for value in {unique_id, linked_id} if value]
        filters = []
        if channel_ids:
            filters.append(models.OutboundCall.ami_channel_id.in_(channel_ids))
        if channel:
            filters.append(models.OutboundCall.asterisk_channel == channel)

        if filters:
            call = (
                db.query(models.OutboundCall)
                .filter(or_(*filters))
                .order_by(models.OutboundCall.id.desc())
                .first()
            )
            if call is not None:
                return call

        destination_number = _destination_from_channel(channel)
        if not destination_number:
            return None
        return (
            db.query(models.OutboundCall)
            .filter(
                models.OutboundCall.destination_number == destination_number,
                models.OutboundCall.status.in_(ACTIVE_CALL_STATUSES),
            )
            .order_by(models.OutboundCall.id.desc())
            .first()
        )


def _destination_from_channel(channel: str | None) -> str | None:
    if not channel:
        return None
    match = PJSIP_DESTINATION_RE.search(channel)
    return match.group("number") if match else None


def _hangup_reason(event: dict[str, str]) -> str:
    cause = event.get("Cause") or event.get("HangupCause") or ""
    cause_text = event.get("Cause-txt") or event.get("CauseTxt") or event.get("HangupCauseTxt") or ""
    reason = " ".join(part for part in [cause, cause_text] if part).strip()
    return reason or "Asterisk Hangup event"


def _originate_failure_reason(event: dict[str, str]) -> str:
    reason = " ".join(
        part
        for part in [
            event.get("Response"),
            event.get("Reason"),
            event.get("Message"),
            event.get("Cause"),
            event.get("Cause-txt"),
        ]
        if part
    ).strip()
    return reason or "Asterisk OriginateResponse failure"


def _is_retryable_originate_failure(reason: str) -> bool:
    normalized = reason.lower()
    retry_tokens = [
        "408",
        "503",
        "timeout",
        "timed out",
        "service unavailable",
        "temporarily unavailable",
        "congestion",
        "chanunavail",
        "no route",
    ]
    return any(token in normalized for token in retry_tokens)


def _safe_event_summary(event: dict[str, str]) -> dict[str, str | None]:
    return {
        "Event": event.get("Event"),
        "Channel": _mask_channel_destination(event.get("Channel")),
        "Uniqueid": event.get("Uniqueid"),
        "Linkedid": event.get("Linkedid"),
        "Cause": event.get("Cause"),
        "Cause-txt": event.get("Cause-txt"),
    }


def _call_snapshot(call: models.OutboundCall) -> dict[str, str | int | None]:
    return {
        "id": call.id,
        "destination_number": mask_phone_number(call.destination_number),
        "status": call.status,
        "ami_channel_id": call.ami_channel_id,
        "asterisk_channel": _mask_channel_destination(call.asterisk_channel),
        "hangup_cause": call.hangup_cause,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
    }


def _mask_channel_destination(channel: str | None) -> str | None:
    destination = _destination_from_channel(channel)
    if not channel or not destination:
        return channel
    return channel.replace(destination, mask_phone_number(destination), 1)


ami_hangup_event_listener = AmiHangupEventListener()
