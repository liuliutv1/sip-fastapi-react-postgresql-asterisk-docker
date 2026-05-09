import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.services.asterisk import AmiError, AsteriskAmiClient
from app.services.call_lifecycle import ACTIVE_CALL_STATUSES, expire_stale_active_calls
from app.services.recording_storage import ensure_recording_dir

ValidationStatus = Literal["ok", "warn", "fail"]


class DeploymentValidationCheck(BaseModel):
    item: str
    status: ValidationStatus
    msg: str


class DeploymentValidationReport(BaseModel):
    status: ValidationStatus
    version: str
    generated_at: datetime
    checks: list[DeploymentValidationCheck] = Field(default_factory=list)


def run_deployment_validation(db: Session) -> DeploymentValidationReport:
    checks = [
        _call_control_check(),
        _hangup_sync_check(db),
        _recording_path_check(),
        _duplicate_call_check(db),
        _provider_trunk_check(db),
    ]
    status: ValidationStatus = "ok"
    if any(check.status == "fail" for check in checks):
        status = "fail"
    elif any(check.status == "warn" for check in checks):
        status = "warn"
    return DeploymentValidationReport(
        status=status,
        version=settings.app_version,
        generated_at=datetime.now(UTC),
        checks=checks,
    )


def _check(item: str, status: ValidationStatus, msg: str) -> DeploymentValidationCheck:
    return DeploymentValidationCheck(item=item, status=status, msg=msg)


def _call_control_check() -> DeploymentValidationCheck:
    endpoint_name = settings.asterisk_outbound_endpoint.strip() or settings.sip_trunk_name
    client = AsteriskAmiClient(timeout=4.0)
    try:
        client.command("core show uptime")
        endpoint = client.command(f"pjsip show endpoint {endpoint_name}")
        contacts = client.command("pjsip show contacts")
    except AmiError as exc:
        return _check("调用正常", "fail", f"Asterisk AMI 或 PJSIP 检查失败：{exc}")

    if "unable to find" in endpoint.lower() or "not found" in endpoint.lower():
        return _check("调用正常", "fail", f"Asterisk 未加载外呼 endpoint {endpoint_name}")
    if settings.sip_vendor_ip not in contacts:
        return _check("调用正常", "fail", f"PJSIP contact 未包含供应商 {settings.sip_vendor_ip}:{settings.sip_vendor_port}")
    return _check("调用正常", "ok", f"AMI 正常，外呼 endpoint {endpoint_name} 已加载，供应商 contact 存在")


def _hangup_sync_check(db: Session) -> DeploymentValidationCheck:
    expired = expire_stale_active_calls(db)
    if expired:
        return _check("挂机同步正常", "warn", f"已自动归档 {expired} 条超时未结束呼叫；请观察 AMI Hangup 事件监听是否持续运行")
    if not settings.asterisk_ami_event_listener_enabled:
        return _check("挂机同步正常", "fail", "ASTERISK_AMI_EVENT_LISTENER_ENABLED 未启用，无法自动同步对方挂机")
    return _check("挂机同步正常", "ok", "AMI Hangup 事件监听已启用，未发现超时占用呼叫")


def _recording_path_check() -> DeploymentValidationCheck:
    try:
        ensure_recording_dir()
        root = Path(settings.recordings_local_dir)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".deploy-write-test-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return _check("录音路径正确", "fail", f"后端无法写入录音目录 {settings.recordings_local_dir}：{exc}")

    if settings.recordings_local_dir != settings.asterisk_recordings_dir:
        return _check(
            "录音路径正确",
            "warn",
            f"后端录音目录 {settings.recordings_local_dir} 与 Asterisk 录音目录 {settings.asterisk_recordings_dir} 不一致，请确认 Docker volume 映射一致",
        )
    return _check("录音路径正确", "ok", f"录音目录 {settings.recordings_local_dir} 可写，并与 Asterisk 路径一致")


def _duplicate_call_check(db: Session) -> DeploymentValidationCheck:
    duplicate_rows = (
        db.query(models.OutboundCall.destination_number, func.count(models.OutboundCall.id))
        .filter(models.OutboundCall.status.in_(ACTIVE_CALL_STATUSES))
        .group_by(models.OutboundCall.destination_number)
        .having(func.count(models.OutboundCall.id) > 1)
        .all()
    )
    if duplicate_rows:
        numbers = ", ".join(f"{number}({count})" for number, count in duplicate_rows[:5])
        return _check("未产生重复呼叫", "fail", f"发现同一号码存在多个进行中呼叫：{numbers}")
    return _check("未产生重复呼叫", "ok", "未发现同一号码重复进行中的外呼")


def _provider_trunk_check(db: Session) -> DeploymentValidationCheck:
    trunks = (
        db.query(models.SipTrunk)
        .filter(
            models.SipTrunk.host == settings.sip_vendor_ip,
            models.SipTrunk.port == settings.sip_vendor_port,
            models.SipTrunk.enabled.is_(True),
        )
        .order_by(models.SipTrunk.id.asc())
        .all()
    )
    if not trunks:
        return _check("供应商线路", "fail", f"没有启用线路指向供应商 {settings.sip_vendor_ip}:{settings.sip_vendor_port}")
    if len(trunks) > 1:
        names = "、".join(trunk.name for trunk in trunks[:5])
        return _check("供应商线路", "warn", f"有 {len(trunks)} 条启用线路指向同一供应商：{names}；系统会按真实 Asterisk endpoint 去重，建议只保留一条")
    return _check("供应商线路", "ok", f"供应商线路 {trunks[0].name} 已启用")
