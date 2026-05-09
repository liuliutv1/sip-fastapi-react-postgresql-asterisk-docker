import logging
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.db import SessionLocal
from app.services.asterisk import AmiError, AsteriskAmiClient

logger = logging.getLogger(__name__)


class SipTrunkHealthMonitor:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.sip_trunk_health_check_enabled:
            logger.info("SIP trunk health monitor is disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="sip-trunk-health-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    check_all_trunks(db)
                    db.commit()
            except Exception as exc:
                logger.warning("SIP trunk health monitor failed: %s", exc)
            self._stop_event.wait(max(settings.sip_trunk_health_check_interval_seconds, 10))


def check_all_trunks(db: Session) -> None:
    trunks = db.query(models.SipTrunk).filter(models.SipTrunk.enabled.is_(True)).order_by(models.SipTrunk.id).all()
    if not trunks:
        return
    client = AsteriskAmiClient(timeout=4.0)
    for trunk in trunks:
        check_trunk_health(db, trunk, client)


def check_trunk_health(db: Session, trunk: models.SipTrunk, client: AsteriskAmiClient | None = None) -> None:
    client = client or AsteriskAmiClient(timeout=4.0)
    now = datetime.now(UTC)
    try:
        endpoint = client.command(f"pjsip show endpoint {trunk.name}")
        if "Unable to find" in endpoint or "not found" in endpoint.lower():
            _set_trunk_health(trunk, "error", f"Asterisk 中找不到 endpoint {trunk.name}", now)
            logger.error("SIP trunk %s health failed: endpoint not found", trunk.name)
            return

        qualify_output = client.command(f"pjsip send qualify {trunk.name}")
        message = _summarize_health(endpoint, qualify_output)
        _set_trunk_health(trunk, "active", message, now)
        logger.info("SIP trunk %s health ok: %s", trunk.name, message)
    except AmiError as exc:
        _set_trunk_health(trunk, "error", f"AMI 健康探测失败：{exc}", now)
        logger.error("SIP trunk %s health check failed: %s", trunk.name, exc)


def _set_trunk_health(trunk: models.SipTrunk, status: str, message: str, checked_at: datetime) -> None:
    trunk.status = status
    trunk.last_health_checked_at = checked_at
    trunk.last_health_message = message[:1000]


def _summarize_health(endpoint: str, qualify_output: str) -> str:
    if "Contact:" in endpoint or "outbound-trunk-aor" in endpoint:
        return "Asterisk endpoint 已加载，已发送 SIP OPTIONS/qualify 探测"
    if qualify_output.strip():
        return qualify_output.splitlines()[0][:300]
    return "Asterisk endpoint 已加载"


sip_trunk_health_monitor = SipTrunkHealthMonitor()
