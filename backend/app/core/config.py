from pathlib import Path
import secrets
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    database_url: str
    migration_database_url: str | None = None
    cors_origins: str = "http://localhost:5173"
    app_env: str = "development"
    jwt_secret_key: str | None = None
    jwt_access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    api_rate_limit_per_minute: int = Field(default=120, ge=10, le=10000)
    login_rate_limit_per_minute: int = Field(default=5, ge=1, le=60)
    service_mutations_enabled: bool | None = None
    monitoring_worker_enabled: bool | None = None
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=300)

    model_config = SettingsConfigDict(
        env_file=(REPOSITORY_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def normalize_postgres_url(cls, value: str | None) -> str | None:
        if value is None or not isinstance(value, str) or not value.strip():
            return value

        url = make_url(value.strip())
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        elif url.drivername == "postgresql+psycopg2":
            raise ValueError("Use the installed psycopg 3 SQLAlchemy driver")
        elif url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use PostgreSQL with psycopg 3")

        host = (url.host or "").lower()
        if host.endswith(".neon.tech"):
            sslmode = (url.query.get("sslmode") or "").lower()
            if not sslmode:
                url = url.update_query_dict({"sslmode": "require"})
            elif sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Neon PostgreSQL URLs must use sslmode=require, verify-ca, or verify-full")
        return url.render_as_string(hide_password=False)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins without paths or wildcards")
        return ",".join(origins)

    @model_validator(mode="after")
    def validate_neon_endpoints(self) -> "Settings":
        self.app_env = self.app_env.strip().lower()
        if self.app_env not in {"development", "test", "production", "worker"}:
            raise ValueError("APP_ENV must be development, test, production, or worker")
        if self.jwt_secret_key is not None and len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        if self.app_env == "production" and not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY is required in production")
        if self.app_env == "production":
            if self.service_mutations_enabled is None:
                self.service_mutations_enabled = False
            if self.monitoring_worker_enabled is None:
                self.monitoring_worker_enabled = False
            for origin in self.cors_origin_list:
                parsed_origin = urlsplit(origin)
                if parsed_origin.scheme != "https":
                    raise ValueError("Production CORS_ORIGINS must use HTTPS")
        else:
            local_defaults = self.app_env in {"development", "test"}
            if self.service_mutations_enabled is None:
                self.service_mutations_enabled = local_defaults
            if self.monitoring_worker_enabled is None:
                self.monitoring_worker_enabled = local_defaults
        application_host = (make_url(self.database_url).host or "").lower()
        if application_host.endswith(".neon.tech") and "-pooler" not in application_host.split(".")[0]:
            raise ValueError("DATABASE_URL must use Neon's pooled endpoint (hostname includes -pooler)")

        if self.migration_database_url:
            migration_host = (make_url(self.migration_database_url).host or "").lower()
            if migration_host.endswith(".neon.tech") and "-pooler" in migration_host.split(".")[0]:
                raise ValueError("MIGRATION_DATABASE_URL must use Neon's direct endpoint without -pooler")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin for origin in self.cors_origins.split(",") if origin]


settings = Settings()
if not settings.jwt_secret_key:
    # Local-only ephemeral secret: tokens expire on process restart and no reusable key is hardcoded.
    settings.jwt_secret_key = secrets.token_urlsafe(48)
