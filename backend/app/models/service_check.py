from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ServiceCheck(Base):
    __tablename__ = "service_checks"
    __table_args__ = (
        CheckConstraint("response_time_ms IS NULL OR response_time_ms >= 0", name="ck_service_checks_response_time_nonnegative"),
        CheckConstraint("status_code IS NULL OR status_code BETWEEN 100 AND 599", name="ck_service_checks_status_code"),
        CheckConstraint(
            "error_type IS NULL OR error_type IN ('timeout', 'connection_error', 'tls_error', 'http_status', 'invalid_target', 'unsupported_check_type')",
            name="ck_service_checks_error_type",
        ),
        CheckConstraint("is_available = false OR error_type IS NULL", name="ck_service_checks_available_without_error"),
        Index("ix_service_checks_service_checked_at", "service_id", "checked_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("monitored_services.id", name="fk_service_checks_service_id_monitored_services", ondelete="RESTRICT"),
        nullable=False,
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(32))

    service: Mapped["MonitoredService"] = relationship(back_populates="checks")
