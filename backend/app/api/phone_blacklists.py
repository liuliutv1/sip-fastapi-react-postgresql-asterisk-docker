from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.db import get_db
from app.services.audit import record_audit_log

router = APIRouter()


@router.get("", response_model=list[schemas.PhoneBlacklistRead])
def list_phone_blacklists(
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    return db.query(models.PhoneBlacklist).order_by(models.PhoneBlacklist.id.desc()).all()


@router.post("", response_model=schemas.PhoneBlacklistRead, status_code=status.HTTP_201_CREATED)
def create_phone_blacklist(
    payload: schemas.PhoneBlacklistCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    entry = models.PhoneBlacklist(
        normalized_number=payload.phone_number,
        reason=payload.reason,
        enabled=payload.enabled,
        created_by_user_id=current_user.id,
    )
    db.add(entry)
    try:
        db.flush()
        record_audit_log(
            db,
            action="phone_blacklist.create",
            resource_type="phone_blacklist",
            resource_id=entry.id,
            user=current_user,
            request=request,
            after=schemas.PhoneBlacklistRead.model_validate(entry).model_dump(mode="json"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phone number is already blacklisted") from exc

    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=schemas.PhoneBlacklistRead)
def update_phone_blacklist(
    entry_id: int,
    payload: schemas.PhoneBlacklistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    entry = _get_entry_or_404(db, entry_id)
    before = schemas.PhoneBlacklistRead.model_validate(entry).model_dump(mode="json")
    data = payload.model_dump(exclude_unset=True)
    if "phone_number" in data:
        data["normalized_number"] = data.pop("phone_number")
    for key, value in data.items():
        setattr(entry, key, value)

    try:
        db.flush()
        record_audit_log(
            db,
            action="phone_blacklist.update",
            resource_type="phone_blacklist",
            resource_id=entry.id,
            user=current_user,
            request=request,
            before=before,
            after=schemas.PhoneBlacklistRead.model_validate(entry).model_dump(mode="json"),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phone number is already blacklisted") from exc

    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phone_blacklist(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    entry = _get_entry_or_404(db, entry_id)
    before = schemas.PhoneBlacklistRead.model_validate(entry).model_dump(mode="json")
    db.delete(entry)
    record_audit_log(
        db,
        action="phone_blacklist.delete",
        resource_type="phone_blacklist",
        resource_id=entry_id,
        user=current_user,
        request=request,
        before=before,
    )
    db.commit()


def _get_entry_or_404(db: Session, entry_id: int) -> models.PhoneBlacklist:
    entry = db.query(models.PhoneBlacklist).filter(models.PhoneBlacklist.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Phone blacklist entry not found")
    return entry
