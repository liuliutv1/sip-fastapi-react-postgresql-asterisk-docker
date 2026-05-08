from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db import get_db
from app.services.audit import record_audit_log

router = APIRouter()


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(models.AppUser).filter(models.AppUser.username == payload.username).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_audit_log(
            db,
            action="auth.login_failed",
            resource_type="auth",
            request=request,
            after={"username": payload.username},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(subject=str(user.id), username=user.username)
    record_audit_log(
        db,
        action="auth.login",
        resource_type="auth",
        user=user,
        request=request,
        resource_id=user.id,
        after={"username": user.username},
    )
    db.commit()
    return schemas.TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=schemas.UserRead)
def me(current_user: models.AppUser = Depends(get_current_user)):
    return current_user
