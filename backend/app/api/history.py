from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Incident, IncidentEvent, MonitoredService, ServiceCheck
from app.schemas.history import IncidentEventRead, IncidentRead, ServiceCheckRead

router = APIRouter(tags=["monitoring history"])


@router.get("/api/services/{service_id}/checks", response_model=list[ServiceCheckRead])
def list_service_checks(
    service_id: UUID,
    limit: int = Query(default=48, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ServiceCheck]:
    if db.get(MonitoredService, service_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored service not found")
    statement = (
        select(ServiceCheck)
        .where(ServiceCheck.service_id == service_id)
        .order_by(ServiceCheck.checked_at.desc(), ServiceCheck.id.desc())
        .limit(limit)
    )
    return list(db.scalars(statement))


@router.get("/api/incidents", response_model=list[IncidentRead])
def list_incidents(
    incident_status: Literal["open", "acknowledged", "resolved"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IncidentRead]:
    statement = select(Incident, MonitoredService.name).join(MonitoredService, Incident.service_id == MonitoredService.id)
    if incident_status is not None:
        statement = statement.where(Incident.status == incident_status)
    rows = db.execute(statement.order_by(Incident.started_at.desc(), Incident.id.desc()).limit(limit)).all()
    return [
        IncidentRead(
            id=incident.id,
            service_id=incident.service_id,
            service_name=service_name,
            title=incident.title,
            description=incident.description,
            severity=incident.severity,
            status=incident.status,
            started_at=incident.started_at,
            acknowledged_at=incident.acknowledged_at,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )
        for incident, service_name in rows
    ]


@router.get("/api/incidents/{incident_id}/events", response_model=list[IncidentEventRead])
def list_incident_events(
    incident_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IncidentEvent]:
    if db.get(Incident, incident_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    statement = (
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at.asc(), IncidentEvent.id.asc())
        .limit(limit)
    )
    return list(db.scalars(statement))
