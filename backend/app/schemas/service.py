from datetime import datetime
from typing import Literal
from uuid import UUID
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SENSITIVE_QUERY_KEYS = {"access_token", "apikey", "api_key", "auth", "authorization", "credential", "credentials", "key", "password", "secret", "signature", "token"}


def validate_target_syntax(check_type: str, target: str) -> None:
    if any(character.isspace() for character in target):
        raise ValueError("target cannot contain whitespace")
    if check_type == "http":
        try:
            parsed = urlsplit(target)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("target must be a valid HTTP or HTTPS URL") from exc
        sensitive_query = any(key.lower().replace("-", "_") in _SENSITIVE_QUERY_KEYS for key, _value in parse_qsl(parsed.query, keep_blank_values=True))
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or sensitive_query or (port is not None and not 1 <= port <= 65535):
            raise ValueError("target must be a valid HTTP or HTTPS URL without credentials or a fragment")
    elif check_type == "tcp":
        raw = target if "://" in target else f"//{target}"
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("target must be a host and port") from exc
        if parsed.scheme not in {"", "tcp"} or not parsed.hostname or port is None or not 1 <= port <= 65535 or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("target must be a host and port without credentials or a path")


class ServiceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    check_type: Literal["http", "tcp"] = "http"
    target: str = Field(min_length=1, max_length=2048)
    check_interval_seconds: int = Field(default=60, ge=5, le=86_400)
    timeout_seconds: int = Field(default=10, gt=0, le=60)
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
        validate_target_syntax(self.check_type, self.target)
        if self.check_type == "tcp" and self.expected_status_code is not None:
            raise ValueError("expected_status_code is only valid for HTTP checks")
        return self


class ServiceCreate(ServiceFields):
    pass


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    check_type: Literal["http", "tcp"] | None = None
    target: str | None = Field(default=None, min_length=1, max_length=2048)
    check_interval_seconds: int | None = Field(default=None, ge=5, le=86_400)
    timeout_seconds: int | None = Field(default=None, gt=0, le=60)
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

    @model_validator(mode="after")
    def validate_target_when_type_is_present(self) -> "ServiceUpdate":
        if self.target is not None and self.check_type is not None:
            validate_target_syntax(self.check_type, self.target)
        return self


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
