from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app import models
from app.core.security import redact_sensitive


def record_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    user: models.AppUser | None = None,
    request: Request | None = None,
    resource_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> models.AuditLog:
    audit_log = models.AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        before_values=redact_sensitive(before) if before else None,
        after_values=redact_sensitive(after) if after else None,
    )
    db.add(audit_log)
    return audit_log
