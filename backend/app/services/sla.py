import logging
from typing import Any

logger = logging.getLogger("sla.events")


def record_sla_event(
    event_type: str,
    severity: str,
    message: str,
    **context: Any,
) -> None:
    logger.warning(
        message,
        extra={
            "event_type": event_type,
            "severity": severity,
            **context,
        },
    )
