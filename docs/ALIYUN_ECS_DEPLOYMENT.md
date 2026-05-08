# 阿里云 ECS 部署 README

本文档面向合法授权的人工外呼系统部署。系统不实现自动批量拨号，不用于骚扰电话，不绕过运营商限制。所有外呼号码必须来自合法业务来源，并启用黑名单、频率限制、审计日志和录音访问权限控制。

## 1. 推荐架构

```text
公网用户 -> HTTPS 443 -> Nginx -> Frontend/Backend
SIP 运营商 <-> Asterisk SIP/RTP
Backend <-> PostgreSQL
Backend <-> Asterisk AMI（内网）
Backend -> 本地 recordings/，可选上传阿里云 OSS 私有 bucket
```

生产环境建议：

- PostgreSQL 不开放公网端口
- Asterisk AMI `5038` 不开放公网端口
- 后台管理只通过 HTTPS 访问
- OSS bucket 使用私有读写，播放/下载通过后端鉴权后生成短期签名 URL
- 录音目录定期备份，并设置保存期限

## 2. ECS 安全组端口

按最小暴露原则配置安全组。

| 端口 | 协议 | 来源 | 用途 |
| --- | --- | --- | --- |
| 22 | TCP | 管理员固定 IP | SSH 运维 |
| 80 | TCP | 0.0.0.0/0 | HTTP，建议仅用于 ACME/跳转 HTTPS |
| 443 | TCP | 0.0.0.0/0 | HTTPS 后台访问 |
| 5060 | UDP | SIP 运营商 IP 段 | SIP 信令 |
| 5060 | TCP | SIP 运营商 IP 段 | 仅在 trunk 使用 TCP/TLS 时开放 |
| 10000-10020 | UDP | SIP 运营商 IP 段 | RTP 媒体流，需与 `rtp.conf` 一致 |
| 5038 | TCP | 不开放公网 | Asterisk AMI，仅容器内或内网访问 |
| 5432 | TCP | 不开放公网 | PostgreSQL，仅容器内访问 |
| 8080 | TCP | 不开放公网 | 开发入口，生产使用 80/443 |

如果运营商要求更大的 RTP 范围，请同时修改：

- ECS 安全组 UDP 范围
- `docker-compose.yml` RTP 端口映射
- `asterisk/config/rtp.conf`

## 3. SIP/RTP NAT 配置

ECS 通常有公网 IP 和内网 IP，Asterisk 在 Docker 容器内运行时需要明确 NAT 参数。建议在 `asterisk/config/pjsip.conf` 的 `transport-udp` 中加入：

```ini
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060
external_signaling_address=<ECS公网IP>
external_media_address=<ECS公网IP>
local_net=<ECS内网CIDR，例如 172.16.0.0/12>
```

同时保持 endpoint 中：

```ini
direct_media=no
```

排查 RTP 单通、无声、双向无声时，优先检查：

- ECS 安全组是否放行 RTP UDP 端口
- Docker 是否映射相同 RTP 端口
- `external_media_address` 是否为公网 IP
- 运营商侧是否限制了媒体源 IP
- `rtp.conf` 中端口范围是否和安全组一致

## 4. HTTPS

生产环境不要裸露 HTTP 管理后台。常见方案：

1. 使用阿里云 SLB/ALB 终止 HTTPS，再转发到 ECS `80`
2. 在 ECS 上使用 Nginx + Certbot 配置证书
3. 使用阿里云 CDN/ESA 等边缘服务终止 HTTPS，再回源到 ECS

如果直接在本项目 Nginx 上配置 HTTPS，需要：

- 挂载证书到容器
- 在 `nginx/default.conf` 增加 `listen 443 ssl`
- 将 80 重定向到 443
- 仅开放 443 给公网

## 5. 环境变量

生产 `.env` 至少修改：

```text
POSTGRES_PASSWORD=<强密码>
JWT_SECRET_KEY=<高强度随机字符串>
SIP_PASSWORD_ENCRYPTION_KEY=<高强度随机字符串>
ADMIN_PASSWORD=<强密码>

ASTERISK_AMI_USERNAME=<非默认用户名>
ASTERISK_AMI_PASSWORD=<强密码>

RECORDINGS_STORAGE_BACKEND=local
RECORDING_RETENTION_DAYS=90
MANUAL_OUTBOUND_RATE_LIMIT_COUNT=5
MANUAL_OUTBOUND_RATE_LIMIT_WINDOW_SECONDS=60
```

启用 OSS 上传时：

```text
RECORDINGS_STORAGE_BACKEND=oss
ALIYUN_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
ALIYUN_OSS_BUCKET=<私有Bucket名称>
ALIYUN_OSS_ACCESS_KEY_ID=<建议使用RAM子账号>
ALIYUN_OSS_ACCESS_KEY_SECRET=<RAM子账号密钥>
ALIYUN_OSS_PREFIX=sip-call-recordings
ALIYUN_OSS_SIGNED_URL_EXPIRE_SECONDS=300
```

RAM 子账号建议只授予目标 bucket 的最小权限：上传、读取、删除指定 prefix 下对象。

## 6. 录音目录权限

默认本地录音目录为项目根目录下 `recordings/`，容器内挂载为 `/recordings`。Linux ECS 上请确保 Asterisk 和 backend 容器可写/可读：

```bash
mkdir -p recordings
chmod 0770 recordings
```

如果遇到权限问题，可临时验证：

```bash
docker compose exec asterisk sh -lc 'touch /recordings/write-test.wav && ls -l /recordings'
docker compose exec backend sh -lc 'ls -l /recordings'
```

## 7. 启动与更新

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

更新代码后：

```bash
docker compose pull
docker compose up --build -d
```

## 8. 日志查看

查看所有服务：

```bash
docker compose logs -f
```

查看后端：

```bash
docker compose logs -f backend
```

查看 Asterisk：

```bash
docker compose logs -f asterisk
docker compose exec asterisk asterisk -rx "pjsip show endpoints"
docker compose exec asterisk asterisk -rx "core show channels"
docker compose exec asterisk asterisk -rx "manager show connected"
```

查看 Nginx：

```bash
docker compose logs -f nginx
```

查看 PostgreSQL：

```bash
docker compose logs -f postgres
```

## 9. 常见故障排查

### 后台无法访问

- 检查 ECS 安全组是否开放 443/80
- 检查 Nginx 容器是否健康：`docker compose ps`
- 检查 Nginx 日志：`docker compose logs -f nginx`
- 如果使用 HTTPS，检查证书路径和域名解析

### 登录失败

- 确认 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`
- 如果已初始化过数据库，修改 `.env` 不会自动改已有管理员密码，需要更新数据库或重新初始化
- 检查后端日志：`docker compose logs -f backend`

### AMI 发起外呼失败

- 确认 backend 可连接 Asterisk AMI：容器内访问 `asterisk:5038`
- 确认 `manager.conf` 用户名密码和 `.env` 一致
- 确认 `sip_trunks.name` 与 Asterisk PJSIP endpoint 名称一致
- 执行：`docker compose exec asterisk asterisk -rx "manager show connected"`

### SIP 注册或出局失败

- 检查 `pjsip.conf` 中 trunk 的认证、AOR、contact
- 检查运营商是否只允许固定源 IP
- 检查安全组是否仅开放给运营商 IP 段
- 执行：`docker compose exec asterisk asterisk -rx "pjsip show registrations"`

### 通话无声音或单通

- 检查 RTP UDP 端口安全组和 Docker 映射
- 检查 `external_media_address`
- 检查 `local_net`
- 检查运营商媒体 IP 是否在安全组来源范围内

### 录音没有生成

- 检查 `recordings/` 目录权限
- 检查 Asterisk 是否支持 `MixMonitor`
- 检查外呼是否真正建立 channel
- 查看 Asterisk 日志：`docker compose logs -f asterisk`
- 查看后台录音记录的 `failure_reason`

### OSS 播放或下载失败

- 确认 bucket 是私有 bucket
- 确认 RAM 子账号有目标 prefix 的读写删权限
- 确认 `ALIYUN_OSS_ENDPOINT` 与 bucket 地域一致
- 如果前端 fetch 跨域签名 URL 失败，给 OSS bucket 配置允许后台域名的 CORS 规则

## 10. 合规与数据保护要求

- 只允许合法授权的人工外呼
- 不接入自动批量拨号
- 不绕过运营商频控、实名和线路限制
- 所有号码必须来自合法业务来源
- 黑名单、频率限制、审计日志必须保持开启
- 录音和电话号码按敏感业务数据处理
- 后台账号最小权限分配
- 定期执行录音保存期限清理
- 不在日志中打印明文 SIP 密码、AMI 密码、OSS 密钥或完整电话号码
