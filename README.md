# 小型 SIP 外呼呼叫中心

这是一个可启动的项目骨架，技术栈为 FastAPI、React、PostgreSQL、Asterisk 和 Docker Compose。它提供了后端 API、前端控制台、PostgreSQL 初始化迁移、Asterisk SIP/AMI 最小配置，以及统一入口 Nginx。

## 目录结构

```text
.
├── asterisk/              # Asterisk 镜像与 SIP/AMI 配置
├── backend/               # FastAPI 后端
├── frontend/              # React + Vite 前端
├── migrations/            # PostgreSQL 初始化 SQL
├── recordings/            # 本地录音保存目录
├── docs/                  # 部署与运维文档
├── nginx/                 # 反向代理配置
├── docker-compose.yml
├── .env.example
└── README.md
```

## 快速启动

```bash
cp .env.example .env
docker compose up --build
```

启动后访问：

- 前端控制台：http://localhost:8080
- API 文档：http://localhost:8080/docs
- 后端健康检查：http://localhost:8080/health

## 默认端口

| 服务 | 地址 |
| --- | --- |
| Nginx | `localhost:8080` |
| FastAPI | `localhost:8000` |
| PostgreSQL | `localhost:5432` |
| Asterisk SIP/UDP | `localhost:5060` |
| Asterisk AMI/TCP | `localhost:5038` |
| Asterisk RTP/UDP | `10000-10020` |

## 默认账号与配置

- PostgreSQL：`callcenter / callcenter`
- Asterisk AMI：`callcenter / callcenter`
- SIP 分机：`6001 / 6001`
- 管理后台：`admin / admin123456`

如果你修改了 PostgreSQL 用户名、密码或数据库名，请同步修改 `DATABASE_URL`。
生产环境请务必修改 `.env` 中的 `JWT_SECRET_KEY`、`SIP_PASSWORD_ENCRYPTION_KEY` 和 `ADMIN_PASSWORD`。

## 后端接口

基础接口已经包含：

- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/health/ready`
- `GET /api/agents`
- `POST /api/agents`
- `GET /api/campaigns`
- `POST /api/campaigns`
- `GET /api/calls`
- `POST /api/calls`
- `GET /api/sip-trunks`
- `POST /api/sip-trunks`
- `GET /api/sip-trunks/{id}`
- `PATCH /api/sip-trunks/{id}`
- `DELETE /api/sip-trunks/{id}`
- `GET /api/sip-peer-whitelists`
- `POST /api/sip-peer-whitelists`
- `GET /api/sip-peer-whitelists/{id}`
- `PATCH /api/sip-peer-whitelists/{id}`
- `DELETE /api/sip-peer-whitelists/{id}`
- `GET /api/outbound-calls`
- `POST /api/outbound-calls`
- `POST /api/outbound-calls/{id}/refresh`
- `POST /api/outbound-calls/{id}/hangup`
- `GET /api/call-recordings`
- `GET /api/call-recordings/{id}`
- `GET /api/call-recordings/{id}/play`
- `GET /api/call-recordings/{id}/download`
- `DELETE /api/call-recordings/{id}`
- `POST /api/call-recordings/retention/purge`
- `GET /api/phone-blacklists`
- `POST /api/phone-blacklists`
- `PATCH /api/phone-blacklists/{id}`
- `DELETE /api/phone-blacklists/{id}`
- `GET /api/audit-logs`

`POST /api/calls` 当前保留为早期外呼任务记录接口。后台页面里的人工外呼使用 `POST /api/outbound-calls`，通过 Asterisk AMI `Originate` 发起单次人工外呼，不包含批量自动外呼。

SIP 线路、SIP 对端白名单和审计日志接口需要 JWT：

```bash
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123456"}'
```

然后在后续请求中使用：

```text
Authorization: Bearer <access_token>
```

## SIP 线路与白名单

`sip_trunks` 字段包括：

- `name`
- `provider_name`
- `description`
- `host`
- `port`
- `transport`
- `username`
- `auth_username`
- `password_encrypted`
- `from_user`
- `from_domain`
- `outbound_proxy`
- `caller_id`
- `codecs`
- `max_channels`
- `registration_enabled`
- `enabled`
- `status`
- `created_at`
- `updated_at`

API 创建/更新时使用 `sip_password` 或兼容字段 `password` 传入 SIP 密码。后端只保存 `password_encrypted`，响应不会返回明文密码或密文，只返回 `password_configured`。

`sip_peer_whitelists` 字段包括：

- `sip_trunk_id`
- `name`
- `peer_cidr`
- `description`
- `enabled`
- `created_at`
- `updated_at`

`peer_cidr` 支持单个 IP 或 CIDR，后端会规范化为 CIDR 格式，例如 `192.0.2.8` 会保存为 `192.0.2.8/32`。

## 审计日志

`audit_logs` 会记录登录、线路、白名单、黑名单和人工外呼的关键操作。审计内容会对包含 `password`、`secret`、`token`、`key`、`credential` 的字段进行脱敏，避免明文 SIP 密码进入日志。

## 人工外呼

后台的“人工外呼”页面支持：

- 选择启用状态的 SIP trunk
- 输入被叫号码和可选主叫号码
- 发起单次 AMI `Originate`
- 显示最近人工外呼状态
- 手动刷新单通呼叫状态
- 通过 AMI `Hangup` 挂断通话
- 管理精确号码黑名单

号码格式会在前后端校验，后端会统一规范化号码。支持示例：`13800138000`、`+8613800138000`、`008613800138000`。

发起外呼前会依次检查：

- SIP trunk 存在且已启用
- 被叫号码格式合法
- 被叫号码不在启用的 `phone_blacklists`
- 当前账号未超过频率限制

频率限制默认是每个账号 60 秒内最多 5 次人工外呼，可通过 `.env` 调整：

```text
MANUAL_OUTBOUND_RATE_LIMIT_COUNT=5
MANUAL_OUTBOUND_RATE_LIMIT_WINDOW_SECONDS=60
```

人工外呼会写入 `outbound_calls`。如果 AMI 发起失败，也会保存一条 `failed` 状态记录和失败原因。

当前 AMI 发起通道格式为：

```text
PJSIP/<被叫号码>@<sip_trunks.name>
```

因此用于外呼的 `sip_trunks.name` 需要与 Asterisk 中的 PJSIP endpoint 名称一致。骨架自带的占位 endpoint 是 `outbound-trunk`。

## 录音与敏感数据

人工外呼成功发起后，系统会通过 Asterisk AMI `MixMonitor` 创建通话录音。默认录音保存到本地共享目录：

```text
recordings/
```

Docker 中 backend 和 Asterisk 都会挂载该目录到 `/recordings`。录音元数据保存在 `call_recordings`，播放和下载必须通过后端鉴权接口，不能直接暴露目录或对象存储 key。

录音安全策略：

- 普通账号只能查看、播放、下载、删除自己的录音
- 管理员可以查看所有录音
- 录音列表只展示脱敏号码
- 播放、下载、删除和列表访问会写入 `audit_logs`
- `RECORDING_RETENTION_DAYS` 控制默认保存期限
- `POST /api/call-recordings/retention/purge` 可按保存期限清理过期录音
- `DELETE /api/call-recordings/{id}` 会删除本地文件和可选 OSS 对象，并保留软删除审计记录

可选启用阿里云 OSS 上传：

```text
RECORDINGS_STORAGE_BACKEND=oss
ALIYUN_OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
ALIYUN_OSS_BUCKET=your-private-bucket
ALIYUN_OSS_ACCESS_KEY_ID=...
ALIYUN_OSS_ACCESS_KEY_SECRET=...
ALIYUN_OSS_PREFIX=sip-call-recordings
```

默认仍保留本地文件。OSS 建议使用私有 bucket，播放和下载通过后端鉴权后生成短期签名 URL。

## 数据库迁移

首次启动 PostgreSQL 时会自动执行 `migrations/` 目录下的 SQL：

```text
migrations/001_init.sql
migrations/002_sip_trunks_auth_audit.sql
migrations/003_outbound_calls_blacklists.sql
migrations/004_call_recordings.sql
```

后端启动时也会执行一次 SQLAlchemy `create_all` 兜底，保证开发环境里服务可以直接启动。

## Asterisk 说明

当前 Asterisk 配置提供：

- UDP SIP 监听：`5060`
- RTP 范围：`10000-10020`
- AMI：`5038`
- 一个测试分机：`6001`
- 一个已配置外呼 trunk：`outbound-trunk`

当前 `outbound-trunk` 已按运营商加白信息配置：

- 主叫号码：`02032730801`
- 被叫前缀：无
- 运营商 IP：`218.245.102.33`
- 运营商端口：`6876`
- ECS 公网 IP：`8.163.96.127`

系统启动时会自动 upsert 这条 SIP trunk，并将 `218.245.102.33/32` 写入 SIP 对端白名单。

## 阿里云 ECS 部署

部署到阿里云 ECS 时，请参考：

```text
docs/ALIYUN_ECS_DEPLOYMENT.md
```
