#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/sip-fastapi-react-postgresql-asterisk-docker}"
APP_URL="${APP_URL:-http://127.0.0.1:8080}"
BRANCH="${BRANCH:-main}"

cd "$APP_DIR"

echo "== 拉取代码 =="
git pull origin "$BRANCH"

touch .env
grep -q '^APP_VERSION=' .env && sed -i 's/^APP_VERSION=.*/APP_VERSION=V1.010/' .env || echo 'APP_VERSION=V1.010' >> .env
grep -q '^PIP_INDEX_URL=' .env || echo 'PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple' >> .env
grep -q '^NPM_CONFIG_REGISTRY=' .env || echo 'NPM_CONFIG_REGISTRY=https://registry.npmmirror.com' >> .env
grep -q '^ASTERISK_OUTBOUND_ENDPOINT=' .env && sed -i 's/^ASTERISK_OUTBOUND_ENDPOINT=.*/ASTERISK_OUTBOUND_ENDPOINT=outbound-trunk/' .env || echo 'ASTERISK_OUTBOUND_ENDPOINT=outbound-trunk' >> .env
grep -q '^ASTERISK_RTP_START=' .env && sed -i 's/^ASTERISK_RTP_START=.*/ASTERISK_RTP_START=10000/' .env || echo 'ASTERISK_RTP_START=10000' >> .env
grep -q '^ASTERISK_RTP_END=' .env && sed -i 's/^ASTERISK_RTP_END=.*/ASTERISK_RTP_END=20000/' .env || echo 'ASTERISK_RTP_END=20000' >> .env
grep -q '^SIP_VENDOR_IP=' .env && sed -i 's/^SIP_VENDOR_IP=.*/SIP_VENDOR_IP=218.245.102.33/' .env || echo 'SIP_VENDOR_IP=218.245.102.33' >> .env
grep -q '^SIP_VENDOR_PORT=' .env && sed -i 's/^SIP_VENDOR_PORT=.*/SIP_VENDOR_PORT=6876/' .env || echo 'SIP_VENDOR_PORT=6876' >> .env
grep -q '^ALIYUN_PUBLIC_IP=' .env && sed -i 's/^ALIYUN_PUBLIC_IP=.*/ALIYUN_PUBLIC_IP=8.163.96.127/' .env || echo 'ALIYUN_PUBLIC_IP=8.163.96.127' >> .env

mkdir -p recordings
chmod -R u+rwX,go+rX recordings

echo "== 构建并启动服务 =="
docker compose up -d --build backend frontend nginx
docker compose up -d asterisk postgres
docker compose restart asterisk backend nginx

echo "== 等待服务健康 =="
for _ in $(seq 1 60); do
  if curl -fsS "${APP_URL%/}/api/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "== 运行部署后验证 =="
APP_URL="$APP_URL" bash scripts/post_deploy_validate.sh
