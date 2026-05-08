from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.db import get_db
from app.services.audit import record_audit_log

router = APIRouter()


@router.get("", response_model=list[schemas.SipPeerWhitelistRead])
def list_sip_peer_whitelists(
    sip_trunk_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    query = db.query(models.SipPeerWhitelist)
    if sip_trunk_id is not None:
        query = query.filter(models.SipPeerWhitelist.sip_trunk_id == sip_trunk_id)
    return query.order_by(models.SipPeerWhitelist.id.desc()).all()


@router.get("/{whitelist_id}", response_model=schemas.SipPeerWhitelistRead)
def get_sip_peer_whitelist(
    whitelist_id: int,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    return _get_whitelist_or_404(db, whitelist_id)


@router.post("", response_model=schemas.SipPeerWhitelistRead, status_code=status.HTTP_201_CREATED)
def create_sip_peer_whitelist(
    payload: schemas.SipPeerWhitelistCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    _ensure_trunk_exists(db, payload.sip_trunk_id)
    whitelist = models.SipPeerWhitelist(**payload.model_dump())
    db.add(whitelist)
    try:
        db.flush()
        record_audit_log(
            db,
            action="sip_peer_whitelist.create",
            resource_type="sip_peer_whitelist",
            resource_id=whitelist.id,
            user=current_user,
            request=request,
            after=_audit_dict(whitelist),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Whitelist CIDR already exists for this trunk") from exc

    db.refresh(whitelist)
    return whitelist


@router.patch("/{whitelist_id}", response_model=schemas.SipPeerWhitelistRead)
def update_sip_peer_whitelist(
    whitelist_id: int,
    payload: schemas.SipPeerWhitelistUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    whitelist = _get_whitelist_or_404(db, whitelist_id)
    before = _audit_dict(whitelist)
    data = payload.model_dump(exclude_unset=True)
    _ensure_trunk_exists(db, data.get("sip_trunk_id"))
    for key, value in data.items():
        setattr(whitelist, key, value)

    try:
        db.flush()
        record_audit_log(
            db,
            action="sip_peer_whitelist.update",
            resource_type="sip_peer_whitelist",
            resource_id=whitelist.id,
            user=current_user,
            request=request,
            before=before,
            after=_audit_dict(whitelist),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Whitelist CIDR already exists for this trunk") from exc

    db.refresh(whitelist)
    return whitelist


@router.delete("/{whitelist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sip_peer_whitelist(
    whitelist_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    whitelist = _get_whitelist_or_404(db, whitelist_id)
    before = _audit_dict(whitelist)
    db.delete(whitelist)
    record_audit_log(
        db,
        action="sip_peer_whitelist.delete",
        resource_type="sip_peer_whitelist",
        resource_id=whitelist_id,
        user=current_user,
        request=request,
        before=before,
    )
    db.commit()


def _get_whitelist_or_404(db: Session, whitelist_id: int) -> models.SipPeerWhitelist:
    whitelist = db.query(models.SipPeerWhitelist).filter(models.SipPeerWhitelist.id == whitelist_id).first()
    if whitelist is None:
        raise HTTPException(status_code=404, detail="SIP peer whitelist not found")
    return whitelist


def _ensure_trunk_exists(db: Session, trunk_id: int | None) -> None:
    if trunk_id is None:
        return
    exists = db.query(models.SipTrunk.id).filter(models.SipTrunk.id == trunk_id).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="SIP trunk not found")


def _audit_dict(whitelist: models.SipPeerWhitelist) -> dict:
    return schemas.SipPeerWhitelistRead.model_validate(whitelist).model_dump(mode="json")
