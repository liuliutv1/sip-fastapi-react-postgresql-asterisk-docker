import socket

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import models
from app.api.deps import get_current_user
from app.core.config import settings
from app.db import get_db
from app.services.asterisk import AmiError, AsteriskAmiClient
from app.services.audit import record_audit_log

router = APIRouter()


def _result(item: str, status: str, msg: str) -> dict[str, str]:
    return {"item": item, "status": status, "msg": msg}


def _ami_command(command: str) -> str:
    return AsteriskAmiClient(timeout=4.0).command(command)


def _outbound_endpoint_name() -> str:
    return settings.asterisk_outbound_endpoint.strip() or settings.sip_trunk_name


def _udp_options_probe(host: str, port: int) -> tuple[str, str]:
    payload = (
        f"OPTIONS sip:healthcheck@{host} SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 0.0.0.0:5060;branch=z9hG4bKsipccui\r\n"
        "From: <sip:healthcheck@localhost>;tag=sipccui\r\n"
        f"To: <sip:healthcheck@{host}>\r\n"
        "Call-ID: sipcc-ui-healthcheck\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)
        try:
            sock.sendto(payload, (host, port))
            data, address = sock.recvfrom(4096)
        except TimeoutError:
            return "warn", "UDP 探测包已发出，但 2 秒内未收到供应商响应；请让供应商核对是否收到来自 ECS 的 SIP 报文"
        except OSError as exc:
            return "fail", f"无法向供应商 {host}:{port}/udp 发送探测包：{exc}"

    first_line = data.decode("utf-8", errors="replace").splitlines()[0] if data else "空响应"
    return "ok", f"收到供应商 {address[0]}:{address[1]} 响应：{first_line}"


@router.get("/check")
def run_system_check(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    try:
        uptime = _ami_command("core show uptime")
        first_line = uptime.splitlines()[0] if uptime else "AMI 已响应"
        results.append(_result("Asterisk 服务状态", "ok", first_line))
    except AmiError as exc:
        results.append(_result("Asterisk 服务状态", "fail", f"Asterisk AMI 连接失败：{exc}"))
        _record_system_check_audit(db, request, current_user, results)
        return results

    try:
        transports = _ami_command("pjsip show transports")
        if f":{settings.asterisk_sip_port}" in transports or "transport-udp" in transports:
            results.append(
                _result(
                    "SIP 信令端口",
                    "warn",
                    f"Asterisk 已配置 SIP UDP {settings.asterisk_sip_port}；后端无法直接读取云安全组，请确认阿里云入方向仅对供应商 IP 开放",
                )
            )
        else:
            results.append(_result("SIP 信令端口", "fail", f"Asterisk 未显示 SIP UDP {settings.asterisk_sip_port} 传输配置"))
    except AmiError as exc:
        results.append(_result("SIP 信令端口", "fail", f"读取 Asterisk SIP 传输配置失败：{exc}"))

    if settings.asterisk_rtp_start <= 10000 and settings.asterisk_rtp_end >= 20000:
        results.append(_result("RTP 端口范围", "ok", f"当前配置覆盖 UDP {settings.asterisk_rtp_start}-{settings.asterisk_rtp_end}"))
    else:
        results.append(
            _result(
                "RTP 端口范围",
                "warn",
                f"当前配置为 UDP {settings.asterisk_rtp_start}-{settings.asterisk_rtp_end}；如运营商要求 10000-20000，请同步修改 .env、Asterisk rtp.conf 和安全组",
            )
        )

    endpoint_name = _outbound_endpoint_name()
    trunk = _find_configured_trunk(db)
    if trunk is None:
        results.append(_result("SIP Trunk 配置", "fail", f"数据库中找不到指向供应商 {settings.sip_vendor_ip}:{settings.sip_vendor_port} 的已启用 SIP 线路"))
    elif not trunk.enabled:
        results.append(_result("SIP Trunk 配置", "fail", f"SIP trunk {trunk.name} 已禁用"))
    elif trunk.host != settings.sip_vendor_ip or trunk.port != settings.sip_vendor_port:
        results.append(
            _result(
                "SIP Trunk 配置",
                "warn",
                f"数据库 trunk 指向 {trunk.host}:{trunk.port}，当前供应商配置为 {settings.sip_vendor_ip}:{settings.sip_vendor_port}",
            )
        )
    else:
        results.append(_result("SIP Trunk 配置", "ok", f"{trunk.name} 已启用并指向供应商 {trunk.host}:{trunk.port}"))

    try:
        endpoint = _ami_command(f"pjsip show endpoint {endpoint_name}")
        contacts = _ami_command("pjsip show contacts")
        if "Unable to find" in endpoint or "not found" in endpoint.lower():
            results.append(_result("PJSIP Trunk 连接", "fail", f"Asterisk 中找不到外呼 endpoint：{endpoint_name}，请检查 pjsip.conf 是否加载并重启 Asterisk"))
        elif settings.sip_vendor_ip not in contacts:
            results.append(_result("PJSIP Trunk 连接", "fail", f"PJSIP contacts 未发现供应商地址 {settings.sip_vendor_ip}"))
        else:
            results.append(_result("PJSIP Trunk 连接", "ok", f"Asterisk 已加载外呼 endpoint {endpoint_name}，contact 包含供应商地址"))
    except AmiError as exc:
        results.append(_result("PJSIP Trunk 连接", "fail", f"读取 PJSIP trunk 状态失败：{exc}"))

    try:
        registrations = _ami_command("pjsip show registrations")
        if "Registered" in registrations:
            results.append(_result("PJSIP 注册状态", "ok", "PJSIP trunk 已注册"))
        elif "No objects found" in registrations or "Objects found: 0" in registrations:
            results.append(_result("PJSIP 注册状态", "warn", "当前未配置注册对象；IP 加白静态对接通常不需要注册，如供应商要求账号注册请补充 registration"))
        elif any(token in registrations for token in ["Rejected", "Unregistered", "Failed", "Timeout"]):
            results.append(_result("PJSIP 注册状态", "fail", "PJSIP registration 状态异常，请检查账号、密码、供应商地址和网络连通性"))
        else:
            results.append(_result("PJSIP 注册状态", "warn", "PJSIP registration 状态不明确，请查看 Asterisk 详细日志"))
    except AmiError as exc:
        results.append(_result("PJSIP 注册状态", "warn", f"读取 PJSIP registration 失败：{exc}"))

    status_value, message = _udp_options_probe(settings.sip_vendor_ip, settings.sip_vendor_port)
    results.append(_result("供应商 SIP 出方向", status_value, message))

    try:
        dialplan = _ami_command("dialplan show outbound")
        if "Dial(PJSIP" in dialplan or endpoint_name:
            results.append(_result("拨号命令预检", "ok", f"不会拨打真实号码；外呼 Originate 格式为 PJSIP/<被叫号码>@{endpoint_name}"))
        else:
            results.append(_result("拨号命令预检", "warn", "未确认 outbound dialplan 中存在 PJSIP Dial，请检查 extensions.conf"))
    except AmiError as exc:
        results.append(_result("拨号命令预检", "warn", f"读取拨号计划失败：{exc}"))

    _record_system_check_audit(db, request, current_user, results)
    return results


def _find_configured_trunk(db: Session) -> models.SipTrunk | None:
    trunk = db.query(models.SipTrunk).filter(models.SipTrunk.name == settings.sip_trunk_name).first()
    if trunk is not None:
        return trunk
    return (
        db.query(models.SipTrunk)
        .filter(
            models.SipTrunk.host == settings.sip_vendor_ip,
            models.SipTrunk.port == settings.sip_vendor_port,
            models.SipTrunk.enabled.is_(True),
        )
        .order_by(models.SipTrunk.id.asc())
        .first()
    )


def _record_system_check_audit(
    db: Session,
    request: Request,
    current_user: models.AppUser,
    results: list[dict[str, str]],
) -> None:
    try:
        record_audit_log(
            db,
            action="system.check",
            resource_type="system",
            user=current_user,
            request=request,
            after={"results": results},
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
