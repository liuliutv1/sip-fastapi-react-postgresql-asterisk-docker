#!/usr/bin/env bash
set -u

APP_NAME="Mini SIP Call Center SIP Health Check"
VERSION="1.0.0"

COMPOSE_DIR="${COMPOSE_DIR:-/opt/sip-fastapi-react-postgresql-asterisk-docker}"
if [[ -f "./docker-compose.yml" ]]; then
  COMPOSE_DIR="$(pwd)"
fi

VENDOR_IP="${VENDOR_IP:-218.245.102.33}"
VENDOR_PORT="${VENDOR_PORT:-6876}"
SIP_PORT="${SIP_PORT:-5060}"
RTP_START="${RTP_START:-10000}"
RTP_END="${RTP_END:-20000}"
TRUNK_NAME="${TRUNK_NAME:-outbound-trunk}"
TRUNK_AOR="${TRUNK_AOR:-outbound-trunk-aor}"
ASTERISK_CONTAINER="${ASTERISK_CONTAINER:-sipcc-asterisk}"
REPORT_FILE="${REPORT_FILE:-sipcc-check-report-$(date +%Y%m%d-%H%M%S).md}"
NO_REPORT=0
SKIP_ALIYUN=0
RUN_LOCAL_ORIGINATE=0
EXPLICIT_RTP_START=0
EXPLICIT_RTP_END=0

OK_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RESET=$'\033[0m'
  C_OK=$'\033[32m'
  C_WARN=$'\033[33m'
  C_FAIL=$'\033[31m'
  C_INFO=$'\033[36m'
  C_BOLD=$'\033[1m'
else
  C_RESET=""
  C_OK=""
  C_WARN=""
  C_FAIL=""
  C_INFO=""
  C_BOLD=""
fi

usage() {
  cat <<EOF
${APP_NAME} v${VERSION}

Usage:
  bash scripts/check_sip_deploy.sh [options]

Options:
  --compose-dir DIR          Docker Compose project directory. Default: ${COMPOSE_DIR}
  --vendor-ip IP            SIP provider IP. Default: ${VENDOR_IP}
  --vendor-port PORT        SIP provider UDP port. Default: ${VENDOR_PORT}
  --sip-port PORT           Local SIP UDP port. Default: ${SIP_PORT}
  --rtp-start PORT          RTP start port. Default: ${RTP_START}
  --rtp-end PORT            RTP end port. Default: ${RTP_END}
  --trunk NAME              Asterisk PJSIP endpoint/trunk name. Default: ${TRUNK_NAME}
  --trunk-aor NAME          Asterisk PJSIP AOR name. Default: ${TRUNK_AOR}
  --container NAME          Asterisk container name. Default: ${ASTERISK_CONTAINER}
  --report FILE             Markdown report path. Default: ${REPORT_FILE}
  --no-report               Do not write Markdown report.
  --skip-aliyun             Skip Aliyun CLI security group checks.
  --run-local-originate     Run a local-only Asterisk originate test. It never calls provider trunk.
  -h, --help                Show this help.

Examples:
  bash scripts/check_sip_deploy.sh
  bash scripts/check_sip_deploy.sh --rtp-start 10000 --rtp-end 20000
  bash scripts/check_sip_deploy.sh --vendor-ip 218.245.102.33 --vendor-port 6876 --trunk outbound-trunk
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-dir)
      COMPOSE_DIR="$2"
      shift 2
      ;;
    --vendor-ip)
      VENDOR_IP="$2"
      shift 2
      ;;
    --vendor-port)
      VENDOR_PORT="$2"
      shift 2
      ;;
    --sip-port)
      SIP_PORT="$2"
      shift 2
      ;;
    --rtp-start)
      RTP_START="$2"
      EXPLICIT_RTP_START=1
      shift 2
      ;;
    --rtp-end)
      RTP_END="$2"
      EXPLICIT_RTP_END=1
      shift 2
      ;;
    --trunk)
      TRUNK_NAME="$2"
      if [[ "$TRUNK_AOR" == "outbound-trunk-aor" ]]; then
        TRUNK_AOR="${TRUNK_NAME}-aor"
      fi
      shift 2
      ;;
    --trunk-aor)
      TRUNK_AOR="$2"
      shift 2
      ;;
    --container)
      ASTERISK_CONTAINER="$2"
      shift 2
      ;;
    --report)
      REPORT_FILE="$2"
      shift 2
      ;;
    --no-report)
      NO_REPORT=1
      shift
      ;;
    --skip-aliyun)
      SKIP_ALIYUN=1
      shift
      ;;
    --run-local-originate)
      RUN_LOCAL_ORIGINATE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

strip_quotes() {
  local value="$1"
  value="${value%$'\r'}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

dotenv_get() {
  local key="$1"
  local file="${COMPOSE_DIR}/.env"
  [[ -f "$file" ]] || return 1
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  [[ -n "$line" ]] || return 1
  strip_quotes "${line#*=}"
}

load_env_defaults() {
  local value
  value="$(dotenv_get ASTERISK_SIP_PORT || true)"
  [[ -n "$value" ]] && SIP_PORT="$value"

  if [[ "$EXPLICIT_RTP_START" -eq 0 ]]; then
    value="$(dotenv_get ASTERISK_RTP_START || true)"
    [[ -n "$value" ]] && RTP_START="$value"
  fi

  if [[ "$EXPLICIT_RTP_END" -eq 0 ]]; then
    value="$(dotenv_get ASTERISK_RTP_END || true)"
    [[ -n "$value" ]] && RTP_END="$value"
  fi
}

report_init() {
  [[ "$NO_REPORT" -eq 0 ]] || return 0
  cat > "$REPORT_FILE" <<EOF
# SIP Deployment Health Check

- Generated: $(date +"%F %T %z")
- Compose dir: \`${COMPOSE_DIR}\`
- Provider: \`${VENDOR_IP}:${VENDOR_PORT}/udp\`
- SIP: \`${SIP_PORT}/udp\`
- RTP: \`${RTP_START}-${RTP_END}/udp\`
- Trunk: \`${TRUNK_NAME}\`

## Results

EOF
}

report_line() {
  [[ "$NO_REPORT" -eq 0 ]] || return 0
  printf '%s\n' "$1" >> "$REPORT_FILE"
}

section() {
  echo
  echo "${C_BOLD}${C_INFO}== $1 ==${C_RESET}"
  report_line ""
  report_line "## $1"
}

info() {
  echo "${C_INFO}INFO${C_RESET}  $1"
  report_line "- INFO: $1"
}

pass() {
  OK_COUNT=$((OK_COUNT + 1))
  echo "${C_OK}OK${C_RESET}    $1"
  report_line "- OK: $1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  echo "${C_WARN}WARN${C_RESET}  $1"
  report_line "- WARN: $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "${C_FAIL}FAIL${C_RESET}  $1"
  report_line "- FAIL: $1"
}

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${COMPOSE_DIR}/docker-compose.yml" "$@"
  elif cmd_exists docker-compose; then
    docker-compose -f "${COMPOSE_DIR}/docker-compose.yml" "$@"
  else
    return 127
  fi
}

asterisk_cli() {
  local command="$1"
  if docker ps --format '{{.Names}}' | grep -Fxq "$ASTERISK_CONTAINER"; then
    docker exec "$ASTERISK_CONTAINER" asterisk -rx "$command" 2>&1
  else
    docker_compose exec -T asterisk asterisk -rx "$command" 2>&1
  fi
}

metadata_get() {
  local path="$1"
  curl -fsS --connect-timeout 1 --max-time 2 "http://100.100.100.200/latest/meta-data/${path}" 2>/dev/null || true
}

check_project_layout() {
  section "项目与工具"

  if [[ -d "$COMPOSE_DIR" && -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
    pass "找到 Docker Compose 项目：${COMPOSE_DIR}"
  else
    fail "找不到 Docker Compose 项目或 docker-compose.yml：${COMPOSE_DIR}"
  fi

  if cmd_exists docker; then
    pass "docker 命令可用：$(docker --version 2>/dev/null)"
  else
    fail "docker 命令不可用"
  fi

  if docker compose version >/dev/null 2>&1; then
    pass "docker compose 插件可用：$(docker compose version 2>/dev/null)"
  elif cmd_exists docker-compose; then
    pass "docker-compose 可用：$(docker-compose --version 2>/dev/null)"
  else
    fail "docker compose / docker-compose 不可用"
  fi

  if cmd_exists python3; then
    pass "python3 可用：$(python3 --version 2>/dev/null)"
  else
    warn "python3 不可用；安全组 JSON 解析与 UDP 探测会降级"
  fi
}

check_aliyun_security_group() {
  section "阿里云安全组"

  if [[ "$SKIP_ALIYUN" -eq 1 ]]; then
    warn "已跳过阿里云安全组检查"
    return 0
  fi

  if ! cmd_exists aliyun; then
    warn "未安装 aliyun CLI，无法在 ECS 内精确读取安全组规则；请手工确认入方向 UDP ${SIP_PORT} 与 ${RTP_START}-${RTP_END} 对 ${VENDOR_IP} 开放"
    return 0
  fi

  if ! cmd_exists python3; then
    warn "已安装 aliyun CLI，但缺少 python3，无法解析安全组规则"
    return 0
  fi

  local region_id instance_id
  region_id="$(metadata_get region-id)"
  instance_id="$(metadata_get instance-id)"

  if [[ -z "$region_id" || -z "$instance_id" ]]; then
    warn "无法读取 ECS 元数据 region-id/instance-id；可能不是在阿里云 ECS 内运行"
    return 0
  fi

  pass "当前 ECS：${instance_id} / ${region_id}"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  local instance_json="${tmp_dir}/instance.json"
  local aliyun_err="${tmp_dir}/aliyun.err"

  if ! aliyun ecs DescribeInstances --RegionId "$region_id" --InstanceIds "[\"${instance_id}\"]" > "$instance_json" 2> "$aliyun_err"; then
    warn "aliyun CLI 调用失败，无法读取安全组。请确认已配置 RAM 角色或 aliyun configure。错误：$(tail -n 1 "$aliyun_err")"
    rm -rf "$tmp_dir"
    return 0
  fi

  local sg_ids
  sg_ids="$(python3 - "$instance_json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

instances = data.get("Instances", {}).get("Instance", [])
if not instances:
    sys.exit(0)

sgs = instances[0].get("SecurityGroupIds", {}).get("SecurityGroupId", [])
print("\n".join(sgs))
PY
)"

  if [[ -z "$sg_ids" ]]; then
    warn "未从实例信息里读取到安全组 ID"
    rm -rf "$tmp_dir"
    return 0
  fi

  info "关联安全组：$(echo "$sg_ids" | tr '\n' ' ')"

  local sg_in_files=()
  local sg_out_files=()
  local sg_id sg_file
  while IFS= read -r sg_id; do
    [[ -n "$sg_id" ]] || continue
    sg_file="${tmp_dir}/${sg_id}-ingress.json"
    if aliyun ecs DescribeSecurityGroupAttribute --RegionId "$region_id" --SecurityGroupId "$sg_id" --Direction ingress > "$sg_file" 2>> "$aliyun_err"; then
      sg_in_files+=("$sg_file")
    else
      warn "读取安全组 ${sg_id} 入方向规则失败：$(tail -n 1 "$aliyun_err")"
    fi

    sg_file="${tmp_dir}/${sg_id}-egress.json"
    if aliyun ecs DescribeSecurityGroupAttribute --RegionId "$region_id" --SecurityGroupId "$sg_id" --Direction egress > "$sg_file" 2>> "$aliyun_err"; then
      sg_out_files+=("$sg_file")
    else
      warn "读取安全组 ${sg_id} 出方向规则失败：$(tail -n 1 "$aliyun_err")"
    fi
  done <<< "$sg_ids"

  if [[ "${#sg_in_files[@]}" -eq 0 ]]; then
    warn "没有可解析的安全组规则"
    rm -rf "$tmp_dir"
    return 0
  fi

  local check_output
  check_output="$(python3 - "$VENDOR_IP" "$SIP_PORT" "$RTP_START" "$RTP_END" "${sg_in_files[@]}" <<'PY'
import ipaddress
import json
import sys

vendor_ip = ipaddress.ip_address(sys.argv[1])
sip_port = int(sys.argv[2])
rtp_start = int(sys.argv[3])
rtp_end = int(sys.argv[4])
files = sys.argv[5:]

def permissions(data):
    return data.get("Permissions", {}).get("Permission", [])

def parse_port_range(value, protocol):
    value = str(value or "")
    if value == "-1/-1":
        return (1, 65535)
    if "/" not in value:
        return None
    left, right = value.split("/", 1)
    try:
        return (int(left), int(right))
    except ValueError:
        return None

def source_contains_vendor(rule):
    cidr = rule.get("SourceCidrIp") or rule.get("Ipv6SourceCidrIp") or ""
    if not cidr:
        return (False, False, "")
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return (False, False, cidr)
    if vendor_ip in net:
        broad = str(net) == "0.0.0.0/0" or net.prefixlen <= 8
        return (True, broad, str(net))
    return (False, False, str(net))

rules = []
for path in files:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sg_id = data.get("SecurityGroupId") or path.rsplit("/", 1)[-1].replace(".json", "")
    for rule in permissions(data):
        policy = str(rule.get("Policy", "")).lower()
        proto = str(rule.get("IpProtocol", "")).lower()
        if policy and policy != "accept":
            continue
        if proto not in ("udp", "all"):
            continue
        port_range = parse_port_range(rule.get("PortRange"), proto)
        if not port_range:
            continue
        contains, broad, source = source_contains_vendor(rule)
        if not contains:
            continue
        start, end = port_range
        rules.append({
            "sg": sg_id,
            "start": start,
            "end": end,
            "source": source,
            "broad": broad,
            "proto": proto,
        })

def interval_text(items):
    return ", ".join(f"{r['sg']} {r['source']} {r['start']}-{r['end']}/{r['proto']}" for r in items)

sip_matches = [r for r in rules if r["start"] <= sip_port <= r["end"]]
if not sip_matches:
    print(f"SIP|fail|未发现允许 {vendor_ip} 访问 UDP {sip_port} 的入方向规则")
elif any(r["broad"] for r in sip_matches):
    print(f"SIP|warn|UDP {sip_port} 已开放，但来源过宽：{interval_text(sip_matches)}")
else:
    print(f"SIP|ok|UDP {sip_port} 已对供应商 IP 开放：{interval_text(sip_matches)}")

rtp_matches = [r for r in rules if not (r["end"] < rtp_start or r["start"] > rtp_end)]
merged = []
for item in sorted(rtp_matches, key=lambda r: (r["start"], r["end"])):
    start = max(item["start"], rtp_start)
    end = min(item["end"], rtp_end)
    if not merged or start > merged[-1][1] + 1:
        merged.append([start, end])
    else:
        merged[-1][1] = max(merged[-1][1], end)

covered = any(start <= rtp_start and end >= rtp_end for start, end in merged)
if not rtp_matches:
    print(f"RTP|fail|未发现允许 {vendor_ip} 访问 UDP {rtp_start}-{rtp_end} 的入方向规则")
elif not covered:
    ranges = ", ".join(f"{s}-{e}" for s, e in merged)
    print(f"RTP|fail|RTP 入方向只覆盖 {ranges}，未完整覆盖 UDP {rtp_start}-{rtp_end}")
elif any(r["broad"] for r in rtp_matches):
    print(f"RTP|warn|UDP {rtp_start}-{rtp_end} 已开放，但来源过宽：{interval_text(rtp_matches)}")
else:
    print(f"RTP|ok|UDP {rtp_start}-{rtp_end} 已对供应商 IP 开放：{interval_text(rtp_matches)}")
PY
)"

  while IFS='|' read -r key status message; do
    [[ -n "$key" ]] || continue
    case "$status" in
      ok) pass "$message" ;;
      warn) warn "$message" ;;
      fail) fail "$message" ;;
      *) info "$message" ;;
    esac
  done <<< "$check_output"

  if [[ "${#sg_out_files[@]}" -eq 0 ]]; then
    warn "没有可解析的出方向安全组规则；将依赖 UDP 探测判断出方向连通性"
  else
    local egress_output
    egress_output="$(python3 - "$VENDOR_IP" "$VENDOR_PORT" "${sg_out_files[@]}" <<'PY'
import ipaddress
import json
import sys

vendor_ip = ipaddress.ip_address(sys.argv[1])
vendor_port = int(sys.argv[2])
files = sys.argv[3:]

def permissions(data):
    return data.get("Permissions", {}).get("Permission", [])

def parse_port_range(value):
    value = str(value or "")
    if value == "-1/-1":
        return (1, 65535)
    if "/" not in value:
        return None
    left, right = value.split("/", 1)
    try:
        return (int(left), int(right))
    except ValueError:
        return None

def dest_contains_vendor(rule):
    cidr = rule.get("DestCidrIp") or rule.get("DestinationCidrIp") or rule.get("Ipv6DestCidrIp") or ""
    if not cidr:
        return (False, False, "")
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return (False, False, cidr)
    if vendor_ip in net:
        broad = str(net) == "0.0.0.0/0" or net.prefixlen <= 8
        return (True, broad, str(net))
    return (False, False, str(net))

matches = []
for path in files:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sg_id = data.get("SecurityGroupId") or path.rsplit("/", 1)[-1].replace(".json", "")
    for rule in permissions(data):
        policy = str(rule.get("Policy", "")).lower()
        proto = str(rule.get("IpProtocol", "")).lower()
        if policy and policy != "accept":
            continue
        if proto not in ("udp", "all"):
            continue
        port_range = parse_port_range(rule.get("PortRange"))
        if not port_range:
            continue
        start, end = port_range
        if not (start <= vendor_port <= end):
            continue
        contains, broad, dest = dest_contains_vendor(rule)
        if not contains:
            continue
        matches.append({
            "sg": sg_id,
            "start": start,
            "end": end,
            "dest": dest,
            "broad": broad,
            "proto": proto,
        })

def text(items):
    return ", ".join(f"{r['sg']} {r['dest']} {r['start']}-{r['end']}/{r['proto']}" for r in items)

if not matches:
    print(f"EGRESS|fail|未发现允许 ECS 出方向访问 {vendor_ip}:{vendor_port}/udp 的安全组规则")
elif any(r["broad"] for r in matches):
    print(f"EGRESS|warn|出方向 UDP {vendor_port} 可访问供应商，但目标范围过宽：{text(matches)}")
else:
    print(f"EGRESS|ok|出方向 UDP {vendor_port} 已允许访问供应商：{text(matches)}")
PY
)"

    while IFS='|' read -r key status message; do
      [[ -n "$key" ]] || continue
      case "$status" in
        ok) pass "$message" ;;
        warn) warn "$message" ;;
        fail) fail "$message" ;;
        *) info "$message" ;;
      esac
    done <<< "$egress_output"
  fi

  rm -rf "$tmp_dir"
}

check_udp_egress() {
  section "供应商 SIP 出方向"

  if cmd_exists ip; then
    local route
    route="$(ip route get "$VENDOR_IP" 2>/dev/null | head -n 1 || true)"
    if [[ -n "$route" ]]; then
      pass "到供应商 IP 的路由存在：${route}"
    else
      warn "无法通过 ip route get 查询到 ${VENDOR_IP} 的路由"
    fi
  fi

  if cmd_exists python3; then
    local udp_output
    udp_output="$(python3 - "$VENDOR_IP" "$VENDOR_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
payload = (
    "OPTIONS sip:healthcheck@{host} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 0.0.0.0:5060;branch=z9hG4bKsipcchealth\r\n"
    "From: <sip:healthcheck@localhost>;tag=sipcchealth\r\n"
    "To: <sip:healthcheck@{host}>\r\n"
    "Call-ID: sipcc-healthcheck-local\r\n"
    "CSeq: 1 OPTIONS\r\n"
    "Max-Forwards: 70\r\n"
    "Content-Length: 0\r\n\r\n"
).format(host=host).encode()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.0)
try:
    sock.sendto(payload, (host, port))
    try:
        data, addr = sock.recvfrom(4096)
        first = data.decode(errors="replace").splitlines()[0] if data else ""
        print(f"ok|收到 UDP/SIP 响应 from {addr[0]}:{addr[1]}：{first}")
    except socket.timeout:
        print("warn|UDP 探测包已发出，但 2 秒内未收到响应；UDP 无连接，这不一定代表失败，请结合供应商侧日志")
except OSError as exc:
    print(f"fail|UDP 探测发送失败：{exc}")
finally:
    sock.close()
PY
)"
    local status="${udp_output%%|*}"
    local message="${udp_output#*|}"
    case "$status" in
      ok) pass "$message" ;;
      warn) warn "$message" ;;
      fail) fail "$message" ;;
      *) info "$udp_output" ;;
    esac
  else
    warn "缺少 python3，跳过 UDP OPTIONS 出方向探测"
  fi
}

check_docker_ports() {
  section "本机端口与 Docker 映射"

  if ! cmd_exists docker; then
    fail "docker 不可用，无法检查容器端口"
    return 0
  fi

  local port_output
  port_output="$(docker port "$ASTERISK_CONTAINER" 2>/dev/null || true)"
  if [[ -z "$port_output" ]]; then
    fail "无法读取容器 ${ASTERISK_CONTAINER} 的端口映射；容器可能未运行"
    return 0
  fi

  if docker port "$ASTERISK_CONTAINER" "5060/udp" 2>/dev/null | grep -q ":${SIP_PORT}$"; then
    pass "Asterisk 容器已发布 SIP UDP ${SIP_PORT}"
  else
    fail "Asterisk 容器未正确发布 SIP UDP ${SIP_PORT}。当前映射：$(echo "$port_output" | tr '\n' '; ')"
  fi

  local rtp_start_ok=0
  local rtp_end_ok=0
  if docker port "$ASTERISK_CONTAINER" "${RTP_START}/udp" >/dev/null 2>&1; then
    rtp_start_ok=1
  fi
  if docker port "$ASTERISK_CONTAINER" "${RTP_END}/udp" >/dev/null 2>&1; then
    rtp_end_ok=1
  fi

  if [[ "$rtp_start_ok" -eq 1 && "$rtp_end_ok" -eq 1 ]]; then
    pass "Asterisk 容器已发布 RTP UDP ${RTP_START}-${RTP_END} 的首尾端口"
  else
    warn "Asterisk 容器未发布 RTP UDP ${RTP_START}-${RTP_END} 的完整首尾端口；当前映射可能与 .env/rtp.conf 不一致"
  fi

  if cmd_exists ss; then
    if ss -lunpt 2>/dev/null | grep -Eq ":${SIP_PORT}([[:space:]]|$)"; then
      pass "宿主机正在监听 UDP ${SIP_PORT}"
    else
      fail "宿主机未监听 UDP ${SIP_PORT}"
    fi
  else
    warn "缺少 ss 命令，跳过宿主机监听检查"
  fi
}

check_asterisk_service() {
  section "Asterisk 服务"

  local container_status
  container_status="$(docker ps --filter "name=^/${ASTERISK_CONTAINER}$" --format '{{.Names}} {{.Status}}' 2>/dev/null || true)"
  if [[ -n "$container_status" ]]; then
    pass "Asterisk 容器运行中：${container_status}"
  else
    fail "Asterisk 容器未运行：${ASTERISK_CONTAINER}"
    return 0
  fi

  local uptime
  uptime="$(asterisk_cli "core show uptime" || true)"
  if echo "$uptime" | grep -Eiq "System uptime|Last reload"; then
    pass "Asterisk CLI 正常：$(echo "$uptime" | head -n 1)"
  else
    fail "Asterisk CLI 无法正常响应：$(echo "$uptime" | head -n 2 | tr '\n' ' ')"
  fi

  local version
  version="$(asterisk_cli "core show version" || true)"
  if [[ -n "$version" ]]; then
    info "$(echo "$version" | head -n 1)"
  fi
}

check_pjsip_trunk() {
  section "PJSIP Trunk"

  local endpoint
  endpoint="$(asterisk_cli "pjsip show endpoint ${TRUNK_NAME}" || true)"
  if echo "$endpoint" | grep -Eiq "Unable to find|not found|No such"; then
    fail "找不到 PJSIP endpoint：${TRUNK_NAME}"
  elif echo "$endpoint" | grep -Fq "$TRUNK_NAME"; then
    pass "PJSIP endpoint 存在：${TRUNK_NAME}"
  else
    warn "PJSIP endpoint 输出不明确：$(echo "$endpoint" | head -n 2 | tr '\n' ' ')"
  fi

  local aor
  aor="$(asterisk_cli "pjsip show aor ${TRUNK_AOR}" || true)"
  if echo "$aor" | grep -Eiq "Unable to find|not found|No such"; then
    fail "找不到 PJSIP AOR：${TRUNK_AOR}"
  elif echo "$aor" | grep -Fq "$VENDOR_IP"; then
    pass "PJSIP AOR 指向供应商：${TRUNK_AOR} -> ${VENDOR_IP}:${VENDOR_PORT}"
  else
    warn "PJSIP AOR 未明显包含供应商 IP：$(echo "$aor" | grep -E "Contact|sip:" | head -n 3 | tr '\n' ' ')"
  fi

  local registrations
  registrations="$(asterisk_cli "pjsip show registrations" || true)"
  if echo "$registrations" | grep -Eiq "Registered"; then
    pass "发现 PJSIP registration 已注册"
  elif echo "$registrations" | grep -Eiq "No objects found|Objects found: 0|No registrations"; then
    warn "未配置 PJSIP registration；当前可能是供应商 IP 加白/静态 Contact 模式，这种对接通常不需要注册"
  elif echo "$registrations" | grep -Eiq "Rejected|Unregistered|Failed|Timeout"; then
    fail "PJSIP registration 状态异常：$(echo "$registrations" | tail -n 5 | tr '\n' ' ')"
  else
    warn "PJSIP registration 输出不明确：$(echo "$registrations" | head -n 5 | tr '\n' ' ')"
  fi

  local contacts
  contacts="$(asterisk_cli "pjsip show contacts" || true)"
  if echo "$contacts" | grep -Fq "$VENDOR_IP"; then
    if echo "$contacts" | grep -Eiq "Avail|Reachable|Created|NonQual"; then
      pass "PJSIP contact 包含供应商地址：${VENDOR_IP}"
    else
      warn "PJSIP contact 包含供应商地址，但状态不明确"
    fi
  else
    fail "PJSIP contacts 未发现供应商地址：${VENDOR_IP}"
  fi

  report_line ""
  report_line "<details><summary>pjsip show endpoint ${TRUNK_NAME}</summary>"
  report_line ""
  report_line '```text'
  report_line "$endpoint"
  report_line '```'
  report_line "</details>"
}

check_safe_dial_dry_run() {
  section "安全拨号检查"

  local dialplan
  dialplan="$(asterisk_cli "dialplan show outbound" || true)"
  if echo "$dialplan" | grep -Fq "Dial(PJSIP"; then
    pass "Asterisk outbound dialplan 存在，包含 PJSIP Dial"
  else
    warn "未确认 outbound dialplan 中存在 PJSIP Dial，请检查 extensions.conf"
  fi

  info "不会拨打真实电话。外呼 dry-run 命令示例：channel originate PJSIP/<被叫号码>@${TRUNK_NAME} application NoOp(SIPCC dry run)"

  if [[ "$RUN_LOCAL_ORIGINATE" -eq 1 ]]; then
    warn "即将执行本地 Local/6001@internal originate；它不走供应商 trunk，但如果 6001 已注册，可能会振铃内部分机"
    local originate_output
    originate_output="$(asterisk_cli "channel originate Local/6001@internal application NoOp SIPCC_HEALTHCHECK" || true)"
    info "本地 originate 输出：$(echo "$originate_output" | tail -n 5 | tr '\n' ' ')"
  fi

  if cmd_exists docker; then
    local logs
    logs="$(docker logs --since 10m "$ASTERISK_CONTAINER" 2>&1 | grep -Ei "originate|dial|pjsip|hangup|warning|error|notice" | tail -n 80 || true)"
    if [[ -n "$logs" ]]; then
      pass "已读取最近 10 分钟 Asterisk 关键日志"
      echo "$logs"
      report_line ""
      report_line "<details><summary>Recent Asterisk logs</summary>"
      report_line ""
      report_line '```text'
      report_line "$logs"
      report_line '```'
      report_line "</details>"
    else
      warn "最近 10 分钟没有匹配到 Asterisk 外呼/PJSIP 关键日志"
    fi
  fi
}

finish_report() {
  section "汇总"

  echo
  echo "${C_BOLD}检查完成：${C_RESET}${C_OK}${OK_COUNT} 正常${C_RESET}, ${C_WARN}${WARN_COUNT} 警告${C_RESET}, ${C_FAIL}${FAIL_COUNT} 失败${C_RESET}"
  report_line ""
  report_line "## Summary"
  report_line ""
  report_line "- OK: ${OK_COUNT}"
  report_line "- WARN: ${WARN_COUNT}"
  report_line "- FAIL: ${FAIL_COUNT}"

  if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo "${C_FAIL}存在失败项，请先处理 FAIL 项，再测试后台人工外呼。${C_RESET}"
  elif [[ "$WARN_COUNT" -gt 0 ]]; then
    echo "${C_WARN}存在警告项；如果外呼无反应，优先查看警告里的安全组、RTP 范围、registration 模式说明。${C_RESET}"
  else
    echo "${C_OK}基础检查通过。${C_RESET}"
  fi

  if [[ "$NO_REPORT" -eq 0 ]]; then
    echo "Markdown 报告：${REPORT_FILE}"
  fi
}

load_env_defaults
report_init

echo "${C_BOLD}${APP_NAME} v${VERSION}${C_RESET}"
echo "Compose: ${COMPOSE_DIR}"
echo "Provider: ${VENDOR_IP}:${VENDOR_PORT}/udp"
echo "SIP: ${SIP_PORT}/udp"
echo "RTP: ${RTP_START}-${RTP_END}/udp"
echo "Trunk: ${TRUNK_NAME} / AOR: ${TRUNK_AOR}"

check_project_layout
check_aliyun_security_group
check_udp_egress
check_docker_ports
check_asterisk_service
check_pjsip_trunk
check_safe_dial_dry_run
finish_report

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi

exit 0
