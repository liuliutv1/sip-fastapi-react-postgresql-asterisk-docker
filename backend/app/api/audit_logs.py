from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.db import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.AuditLogRead])
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    resource_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    query = db.query(models.AuditLog)
    if resource_type:
        query = query.filter(models.AuditLog.resource_type == resource_type)
    return query.order_by(models.AuditLog.id.desc()).limit(limit).all()
