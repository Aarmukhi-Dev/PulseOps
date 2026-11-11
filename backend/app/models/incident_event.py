from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'acknowledged', 'status_changed', 'severity_changed', 'commented', 'resolved', 'reopened')",
            name="ck_incident_events_event_type",
        ),
        Index("ix_incident_events_incident_created_id", "incident_id", "created_at", "id"),
        Index("ix_incident_events_actor_user_id", "actor_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", name="fk_incident_events_incident_id_incidents", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_incident_events_actor_user_id_users", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    incident: Mapped["Incident"] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship(back_populates="incident_events")
