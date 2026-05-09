import json
import logging

from app.core.monitoring import JsonLogFormatter


def test_json_log_formatter_includes_api_fields():
    record = logging.LogRecord(
        name="api.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="api_request",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"
    record.method = "GET"
    record.path = "/api/health/live"
    record.status_code = 200
    record.duration_ms = 12.5

    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "api_request"
    assert payload["request_id"] == "req-1"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.5
