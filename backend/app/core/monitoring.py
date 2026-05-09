import json
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.services.sla import record_sla_event


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status_code", "duration_ms", "event_type", "severity"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.handlers = [handler]


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.app_version,
        traces_sample_rate=max(0.0, min(settings.sentry_traces_sample_rate, 1.0)),
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )


class ApiLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger = logging.getLogger("api.access")
            logger.info(
                "api_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            if status_code >= 500:
                record_sla_event(
                    "api_error",
                    "error",
                    f"{request.method} {request.url.path} returned {status_code}",
                    request_id=request_id,
                    status_code=status_code,
                    duration_ms=duration_ms,
                )
            elif duration_ms >= settings.sla_slow_request_ms:
                record_sla_event(
                    "api_slow_request",
                    "warn",
                    f"{request.method} {request.url.path} took {duration_ms}ms",
                    request_id=request_id,
                    status_code=status_code,
                    duration_ms=duration_ms,
                )
