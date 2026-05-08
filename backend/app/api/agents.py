from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.AgentRead])
def list_agents(db: Session = Depends(get_db)):
    return db.query(models.Agent).order_by(models.Agent.id).all()


@router.post("", response_model=schemas.AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(payload: schemas.AgentCreate, db: Session = Depends(get_db)):
    agent = models.Agent(**payload.model_dump())
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Agent extension already exists") from exc
    db.refresh(agent)
    return agent
