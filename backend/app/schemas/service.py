from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ServiceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    check_type: Literal["http", "tcp"] = "http"
    target: str = Field(min_length=1, max_length=2048)
    check_interval_seconds: int = Field(default=60, gt=0, le=2_147_483_647)
    timeout_seconds: int = Field(default=10, gt=0, le=2_147_483_647)
    expected_status_code: int | None = Field(default=None, ge=100, le=599)
    is_enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must contain a non-whitespace character")
        return value

    @field_validator("target")
    @classmethod
    def normalize_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target must contain a non-whitespace character")
        return value

    @model_validator(mode="after")
    def validate_http_status(self) -> "ServiceFields":
        if self.check_type == "tcp" and self.expected_status_code is not None:
            raise ValueError("expected_status_code is only valid for HTTP checks")
        return self


class ServiceCreate(ServiceFields):
    created_by: UUID


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    check_type: Literal["http", "tcp"] | None = None
    target: str | None = Field(default=None, min_length=1, max_length=2048)
    check_interval_seconds: int | None = Field(default=None, gt=0, le=2_147_483_647)
    timeout_seconds: int | None = Field(default=None, gt=0, le=2_147_483_647)
    expected_status_code: int | None = Field(default=None, ge=100, le=599)
    is_enabled: bool | None = None

    @field_validator("name", "target")
    @classmethod
    def normalize_nonempty_strings(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("this field cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("this field must contain a non-whitespace character")
        return value

    @field_validator("check_type", "check_interval_seconds", "timeout_seconds", "is_enabled")
    @classmethod
    def reject_null_for_nonnullable_fields(cls, value):
        if value is None:
            raise ValueError("this field cannot be null")
        return value


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    check_type: Literal["http", "tcp"]
    target: str
    check_interval_seconds: int
    timeout_seconds: int
    expected_status_code: int | None
    is_enabled: bool
    current_status: Literal["unknown", "healthy", "unhealthy"]
    last_checked_at: datetime | None
    last_response_time_ms: int | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
