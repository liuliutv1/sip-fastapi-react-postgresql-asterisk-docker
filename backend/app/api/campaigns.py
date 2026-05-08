from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.CampaignRead])
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(models.Campaign).order_by(models.Campaign.id.desc()).all()


@router.post("", response_model=schemas.CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: schemas.CampaignCreate, db: Session = Depends(get_db)):
    campaign = models.Campaign(**payload.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign
