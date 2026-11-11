from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ServiceCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_id: UUID
    checked_at: datetime
    is_available: bool
    response_time_ms: int | None
    status_code: int | None
    error_type: str | None


class IncidentRead(BaseModel):
    id: UUID
    service_id: UUID
    service_name: str
    title: str
    description: str | None
    severity: str
    status: Literal["open", "acknowledged", "resolved"]
    started_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    actor_user_id: UUID | None
    event_type: str
    payload: dict[str, object]
    created_at: datetime
