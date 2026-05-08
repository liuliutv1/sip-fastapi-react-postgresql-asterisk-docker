from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.security import hash_password


def ensure_default_admin(db: Session) -> None:
    exists = db.query(models.AppUser).filter(models.AppUser.username == settings.admin_username).first()
    if exists:
        return

    db.add(
        models.AppUser(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            is_active=True,
            is_admin=True,
        )
    )
    db.commit()
