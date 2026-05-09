#!/usr/bin/env bash
set -Eeuo pipefail

APP_URL="${APP_URL:-http://127.0.0.1:8080}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123456}"
REPORT_FILE="${REPORT_FILE:-post-deploy-validation-$(date +%Y%m%d-%H%M%S).json}"

if ! command -v curl >/dev/null 2>&1; then
  echo "FAIL curl 未安装，无法执行部署后验证" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL python3 未安装，无法解析验证结果" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

login_json="${tmp_dir}/login.json"
validation_json="${tmp_dir}/validation.json"

echo "== 部署后自动验证 =="
echo "API: ${APP_URL}"

login_code="$(
  curl -sS -o "$login_json" -w "%{http_code}" \
    -X POST "${APP_URL%/}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${ADMIN_USERNAME}\",\"password\":\"${ADMIN_PASSWORD}\"}"
)"

if [[ "$login_code" != "200" ]]; then
  echo "FAIL 登录失败，HTTP ${login_code}"
  cat "$login_json"
  exit 1
fi

token="$(python3 - "$login_json" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(data.get("access_token", ""))
PY
)"

if [[ -z "$token" ]]; then
  echo "FAIL 登录响应中没有 access_token"
  cat "$login_json"
  exit 1
fi

validation_code="$(
  curl -sS -o "$validation_json" -w "%{http_code}" \
    -X POST "${APP_URL%/}/api/system/validate-deployment" \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/json"
)"

cp "$validation_json" "$REPORT_FILE"

if [[ "$validation_code" != "200" ]]; then
  echo "FAIL 验证 API 请求失败，HTTP ${validation_code}"
  cat "$validation_json"
  exit 1
fi

python3 - "$validation_json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"版本: {data.get('version')}")
print(f"总体状态: {data.get('status')}")
print("")

failed = []
for check in data.get("checks", []):
    status = check.get("status")
    icon = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(status, "UNKNOWN")
    line = f"{icon} {check.get('item')}: {check.get('msg')}"
    print(line)
    if status == "fail":
        failed.append(line)

if data.get("status") == "fail" or failed:
    print("")
    print("部署后验证失败，阻止部署完成。失败原因：")
    for item in failed:
        print(f"- {item}")
    sys.exit(1)

if data.get("status") == "warn":
    print("")
    print("部署后验证通过但存在警告，请上线前人工确认警告项。")
else:
    print("")
    print("部署后验证通过：调用正常、挂机同步正常、录音路径正确、未产生重复呼叫。")
PY

echo "报告已保存：${REPORT_FILE}"
