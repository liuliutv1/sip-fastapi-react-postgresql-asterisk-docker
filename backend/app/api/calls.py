from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.services.asterisk import build_originate_preview

router = APIRouter()


@router.get("", response_model=list[schemas.CallRead])
def list_calls(db: Session = Depends(get_db)):
    return db.query(models.CallRecord).order_by(models.CallRecord.id.desc()).limit(100).all()


@router.post("", response_model=schemas.CallRead, status_code=status.HTTP_201_CREATED)
def create_call(payload: schemas.CallCreate, db: Session = Depends(get_db)):
    call = models.CallRecord(**payload.model_dump(), status="queued")
    db.add(call)
    db.commit()
    db.refresh(call)

    build_originate_preview(destination=call.destination)
    return call
