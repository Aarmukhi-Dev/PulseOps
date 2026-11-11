from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models import MonitoredService, User
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate, validate_target_syntax

router = APIRouter(prefix="/api/services", tags=["services"])


def _ensure_mutations_enabled() -> None:
    if not settings.service_mutations_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service management is disabled by deployment policy")


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MonitoredService:
    _ensure_mutations_enabled()
    service = MonitoredService(**payload.model_dump(), created_by=user.id)
    db.add(service)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Could not create monitored service",
        ) from exc
    db.refresh(service)
    return service


@router.get("", response_model=list[ServiceRead])
def list_services(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[MonitoredService]:
    return list(db.scalars(select(MonitoredService).where(MonitoredService.created_by == user.id).order_by(MonitoredService.created_at.desc(), MonitoredService.id)))


@router.get("/{service_id}", response_model=ServiceRead)
def get_service(service_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MonitoredService:
    service = db.scalar(select(MonitoredService).where(MonitoredService.id == service_id, MonitoredService.created_by == user.id))
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")
    return service


@router.patch("/{service_id}", response_model=ServiceRead)
def update_service(service_id: UUID, payload: ServiceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> MonitoredService:
    _ensure_mutations_enabled()
    service = db.scalar(select(MonitoredService).where(MonitoredService.id == service_id, MonitoredService.created_by == user.id))
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")

    changes = payload.model_dump(exclude_unset=True)
    if "target" in changes:
        try:
            validate_target_syntax(changes.get("check_type", service.check_type), changes["target"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    for field, value in changes.items():
        setattr(service, field, value)

    db.commit()
    db.refresh(service)
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _ensure_mutations_enabled()
    service = db.scalar(select(MonitoredService).where(MonitoredService.id == service_id, MonitoredService.created_by == user.id))
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
