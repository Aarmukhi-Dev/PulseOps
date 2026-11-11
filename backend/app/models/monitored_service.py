from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MonitoredService(Base):
    __tablename__ = "monitored_services"
    __table_args__ = (
        CheckConstraint("check_type IN ('http', 'tcp')", name="ck_monitored_services_check_type"),
        CheckConstraint("check_interval_seconds > 0", name="ck_monitored_services_interval_positive"),
        CheckConstraint("timeout_seconds > 0", name="ck_monitored_services_timeout_positive"),
        CheckConstraint("current_status IN ('unknown', 'healthy', 'unhealthy')", name="ck_monitored_services_current_status"),
        CheckConstraint(
            "last_response_time_ms IS NULL OR last_response_time_ms >= 0",
            name="ck_monitored_services_last_response_time_nonnegative",
        ),
        Index("ix_monitored_services_is_enabled", "is_enabled"),
        Index("ix_monitored_services_created_by", "created_by"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'http'"))
    target: Mapped[str] = mapped_column(String(2048), nullable=False)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    expected_status_code: Mapped[int | None] = mapped_column(Integer)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    current_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'unknown'"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_response_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_monitored_services_created_by_users", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    creator: Mapped["User"] = relationship(back_populates="services")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="service", passive_deletes=True)
    checks: Mapped[list["ServiceCheck"]] = relationship(back_populates="service", passive_deletes=True)
