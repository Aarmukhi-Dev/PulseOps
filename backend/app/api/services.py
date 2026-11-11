from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import MonitoredService
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate

router = APIRouter(prefix="/api/services", tags=["services"])


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db)) -> MonitoredService:
    service = MonitoredService(**payload.model_dump())
    db.add(service)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="created_by must reference an existing user",
        ) from exc
    db.refresh(service)
    return service


@router.get("", response_model=list[ServiceRead])
def list_services(db: Session = Depends(get_db)) -> list[MonitoredService]:
    return list(db.scalars(select(MonitoredService).order_by(MonitoredService.created_at.desc(), MonitoredService.id)))


@router.get("/{service_id}", response_model=ServiceRead)
def get_service(service_id: UUID, db: Session = Depends(get_db)) -> MonitoredService:
    service = db.get(MonitoredService, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")
    return service


@router.patch("/{service_id}", response_model=ServiceRead)
def update_service(service_id: UUID, payload: ServiceUpdate, db: Session = Depends(get_db)) -> MonitoredService:
    service = db.get(MonitoredService, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)

    db.commit()
    db.refresh(service)
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: UUID, db: Session = Depends(get_db)) -> Response:
    service = db.get(MonitoredService, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")

    db.delete(service)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This service has check or incident history and cannot be deleted",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
