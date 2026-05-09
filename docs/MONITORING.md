# 监控、日志与 SLA 规范

## Sentry

后端通过 `sentry-sdk[fastapi]` 集成，前端通过 `@sentry/react` 集成。

生产环境建议配置：

```env
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.05
VITE_SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
```

如果 DSN 为空，系统不会上报错误，不影响本地和内网部署。

## 日志格式

后端日志使用 JSON Lines，每行一条事件：

```json
{
  "ts": "2026-05-09T20:00:00+0800",
  "level": "INFO",
  "logger": "api.access",
  "message": "api_request",
  "request_id": "8f4a...",
  "method": "POST",
  "path": "/api/outbound-calls",
  "status_code": 201,
  "duration_ms": 42.18
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `ts` | 服务端时间 |
| `level` | `INFO` / `WARN` / `ERROR` |
| `logger` | 日志来源，例如 `api.access`、`sla.events` |
| `request_id` | 请求 ID，可由 `X-Request-Id` 传入 |
| `method` / `path` | API 方法和路径 |
| `status_code` | HTTP 状态码 |
| `duration_ms` | 请求耗时 |
| `event_type` | SLA 事件类型 |
| `severity` | SLA 严重级别 |

所有密码、密钥、token、credential 字段进入审计日志前会脱敏。

## SLA 事件

当前会自动记录：

- `api_error`：HTTP 5xx
- `api_slow_request`：API 耗时超过 `SLA_SLOW_REQUEST_MS`

建议告警阈值：

| 指标 | 建议阈值 |
| --- | --- |
| 5xx 错误率 | 5 分钟内 > 1% |
| 外呼接口 P95 | > 1500ms |
| Asterisk AMI 连接失败 | 任意一次触发告警 |
| 挂机未同步 | 进行中呼叫超过 10 分钟未结束 |
| 录音失败率 | 30 分钟内 > 2% |

## 仪表盘建议

1. API 总览：请求量、错误率、P95/P99 耗时。
2. 外呼链路：发起数、失败数、重复拦截数、平均接通后挂机同步时间。
3. Asterisk：AMI 连接状态、PJSIP endpoint/contact 状态、Hangup 事件数。
4. 录音：录音中、已完成、失败数量；录音目录可写状态。
5. 安全：登录失败、录音播放/下载审计、SIP 线路变更审计。

## 部署后验证

部署完成后必须执行：

```bash
APP_URL=http://127.0.0.1:8080 \
ADMIN_USERNAME=admin \
ADMIN_PASSWORD='你的密码' \
bash scripts/post_deploy_validate.sh
```

验证失败会以非 0 状态码退出，可用于阻止部署流程完成。
