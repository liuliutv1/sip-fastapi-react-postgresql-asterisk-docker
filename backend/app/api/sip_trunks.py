from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.deps import get_current_user
from app.core.security import encrypt_secret
from app.db import get_db
from app.services.audit import record_audit_log

router = APIRouter()


def serialize_trunk(trunk: models.SipTrunk) -> schemas.SipTrunkRead:
    return schemas.SipTrunkRead(
        id=trunk.id,
        name=trunk.name,
        provider_name=trunk.provider_name,
        description=trunk.description,
        host=trunk.host,
        port=trunk.port,
        transport=trunk.transport,
        username=trunk.username,
        auth_username=trunk.auth_username,
        from_user=trunk.from_user,
        from_domain=trunk.from_domain,
        outbound_proxy=trunk.outbound_proxy,
        caller_id=trunk.caller_id,
        codecs=_split_codecs(trunk.codecs),
        max_channels=trunk.max_channels,
        registration_enabled=trunk.registration_enabled,
        enabled=trunk.enabled,
        status=trunk.status,
        password_configured=bool(trunk.password_encrypted),
        last_health_checked_at=trunk.last_health_checked_at,
        last_health_message=trunk.last_health_message,
        created_at=trunk.created_at,
        updated_at=trunk.updated_at,
    )


def trunk_audit_dict(trunk: models.SipTrunk) -> dict:
    data = serialize_trunk(trunk).model_dump(mode="json")
    data["sip_password"] = "[CONFIGURED]" if trunk.password_encrypted else None
    return data


@router.get("", response_model=list[schemas.SipTrunkRead])
def list_sip_trunks(
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    trunks = db.query(models.SipTrunk).order_by(models.SipTrunk.id.desc()).all()
    return [serialize_trunk(trunk) for trunk in trunks]


@router.get("/{trunk_id}", response_model=schemas.SipTrunkRead)
def get_sip_trunk(
    trunk_id: int,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    trunk = _get_trunk_or_404(db, trunk_id)
    return serialize_trunk(trunk)


@router.post("", response_model=schemas.SipTrunkRead, status_code=status.HTTP_201_CREATED)
def create_sip_trunk(
    payload: schemas.SipTrunkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    data = payload.model_dump(exclude={"sip_password"})
    trunk = models.SipTrunk(**_to_model_data(data))
    if payload.sip_password:
        trunk.password_encrypted = encrypt_secret(payload.sip_password)

    db.add(trunk)
    try:
        db.flush()
        record_audit_log(
            db,
            action="sip_trunk.create",
            resource_type="sip_trunk",
            resource_id=trunk.id,
            user=current_user,
            request=request,
            after=trunk_audit_dict(trunk),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SIP trunk name already exists") from exc

    db.refresh(trunk)
    return serialize_trunk(trunk)


@router.patch("/{trunk_id}", response_model=schemas.SipTrunkRead)
def update_sip_trunk(
    trunk_id: int,
    payload: schemas.SipTrunkUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    trunk = _get_trunk_or_404(db, trunk_id)
    before = trunk_audit_dict(trunk)
    data = payload.model_dump(exclude_unset=True, exclude={"sip_password"})
    for key, value in _to_model_data(data).items():
        setattr(trunk, key, value)
    if payload.sip_password:
        trunk.password_encrypted = encrypt_secret(payload.sip_password)

    try:
        db.flush()
        record_audit_log(
            db,
            action="sip_trunk.update",
            resource_type="sip_trunk",
            resource_id=trunk.id,
            user=current_user,
            request=request,
            before=before,
            after=trunk_audit_dict(trunk),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SIP trunk name already exists") from exc

    db.refresh(trunk)
    return serialize_trunk(trunk)


@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sip_trunk(
    trunk_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.AppUser = Depends(get_current_user),
):
    trunk = _get_trunk_or_404(db, trunk_id)
    before = trunk_audit_dict(trunk)
    db.delete(trunk)
    record_audit_log(
        db,
        action="sip_trunk.delete",
        resource_type="sip_trunk",
        resource_id=trunk_id,
        user=current_user,
        request=request,
        before=before,
    )
    db.commit()


def _get_trunk_or_404(db: Session, trunk_id: int) -> models.SipTrunk:
    trunk = db.query(models.SipTrunk).filter(models.SipTrunk.id == trunk_id).first()
    if trunk is None:
        raise HTTPException(status_code=404, detail="SIP trunk not found")
    return trunk


def _to_model_data(data: dict) -> dict:
    normalized = dict(data)
    if "codecs" in normalized and normalized["codecs"] is not None:
        normalized["codecs"] = ",".join(normalized["codecs"])
    return normalized


def _split_codecs(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
