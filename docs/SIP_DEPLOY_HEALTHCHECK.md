# SIP 部署自动检查脚本

脚本位置：

```bash
scripts/check_sip_deploy.sh
```

它用于在阿里云 ECS 上排查“小型 SIP 外呼呼叫中心”外呼无反应、Asterisk 未连通、SIP/RTP 端口未开放等问题。脚本不会拨打真实电话，默认只做连通性检查、Asterisk/PJSIP 状态读取和外呼命令 dry-run。

## 一键运行

在 ECS 上执行：

```bash
cd /opt/sip-fastapi-react-postgresql-asterisk-docker
chmod +x scripts/check_sip_deploy.sh
sudo bash scripts/check_sip_deploy.sh
```

默认供应商信息：

```text
供应商 IP: 218.245.102.33
供应商 SIP 端口: 6876/udp
本机 SIP 端口: 5060/udp
PJSIP trunk: outbound-trunk
```

脚本会优先读取项目 `.env` 中的 `ASTERISK_RTP_START` 和 `ASTERISK_RTP_END`。如果你要按运营商或安全组要求检查 `10000-20000/udp`，执行：

```bash
sudo bash scripts/check_sip_deploy.sh --rtp-start 10000 --rtp-end 20000
```

## 检查内容

- Docker Compose 项目是否存在。
- Docker、docker compose、python3 是否可用。
- 如安装并配置了 `aliyun` CLI：
  - 入方向是否允许供应商 IP 访问 `5060/udp`。
  - 入方向是否允许供应商 IP 访问 RTP 端口范围。
  - 出方向是否允许 ECS 访问供应商 `218.245.102.33:6876/udp`。
- ECS 到供应商 SIP 端口的 UDP OPTIONS 探测。
- Asterisk 容器是否运行。
- Asterisk CLI 是否可用。
- PJSIP endpoint、AOR、contact、registration 状态。
- outbound dialplan 是否存在。
- 最近 10 分钟 Asterisk 外呼/PJSIP 关键日志。

## 阿里云安全组精确检查

ECS 机器内部无法只靠本机命令精确判断“安全组入方向是否开放”。如果需要脚本自动读取安全组，请在 ECS 上安装并配置阿里云 CLI，推荐给 ECS 绑定最小权限 RAM 角色，允许读取 ECS 实例和安全组信息。

如果没有 `aliyun` CLI，脚本会输出 `WARN`，并继续检查 Docker、Asterisk、PJSIP 和 UDP 探测。

## 常用命令

指定供应商：

```bash
sudo bash scripts/check_sip_deploy.sh \
  --vendor-ip 218.245.102.33 \
  --vendor-port 6876 \
  --trunk outbound-trunk \
  --trunk-aor outbound-trunk-aor
```

生成指定 Markdown 报告：

```bash
sudo bash scripts/check_sip_deploy.sh --report /tmp/sipcc-check.md
```

跳过阿里云安全组检查：

```bash
sudo bash scripts/check_sip_deploy.sh --skip-aliyun
```

执行本地 Asterisk originate 测试：

```bash
sudo bash scripts/check_sip_deploy.sh --run-local-originate
```

这个测试只使用 `Local/6001@internal`，不会走供应商 trunk，也不会拨打真实公网号码。如果内部分机 `6001` 已注册，可能会振铃内部分机。

## 结果判断

- `OK`：检查项正常。
- `WARN`：不一定导致外呼失败，但需要结合供应商侧日志或当前配置确认。
- `FAIL`：优先处理，通常会导致外呼无反应或无法接通。

重点关注：

- `未发现允许供应商 IP 访问 UDP 5060 的入方向规则`
- `RTP 入方向未完整覆盖`
- `未发现允许 ECS 出方向访问供应商 SIP 端口的安全组规则`
- `Asterisk 容器未运行`
- `找不到 PJSIP endpoint`
- `PJSIP contacts 未发现供应商地址`

## 外呼无反应时的下一步

如果脚本显示端口和服务都正常，但页面外呼仍没有反应，请继续查看：

```bash
cd /opt/sip-fastapi-react-postgresql-asterisk-docker
docker compose logs --tail=120 backend
docker compose logs --tail=120 asterisk
docker compose exec asterisk asterisk -rx "pjsip show endpoints"
docker compose exec asterisk asterisk -rx "pjsip show contacts"
```

然后把脚本输出和最近日志发给供应商核对：是否收到来自 `8.163.96.127` 的 SIP 报文，是否要求特定主叫号码、From 域、鉴权账号或 RTP 端口范围。
