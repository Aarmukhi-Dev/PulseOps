import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings


def test_neon_application_url_uses_psycopg3_and_requires_tls() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://app_user:example-password@ep-prod-pooler.ap-southeast-1.aws.neon.tech/pulseops",
    )

    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "ep-prod-pooler.ap-southeast-1.aws.neon.tech"
    assert url.query["sslmode"] == "require"


def test_alembic_can_use_a_separate_direct_neon_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgres://app_user:example-password@ep-prod-pooler.ap-southeast-1.aws.neon.tech/pulseops?sslmode=require",
        migration_database_url="postgres://migration_user:example-password@ep-prod.ap-southeast-1.aws.neon.tech/pulseops?sslmode=require",
    )

    assert make_url(settings.database_url).host.startswith("ep-prod-pooler")
    assert make_url(settings.migration_database_url).host == "ep-prod.ap-southeast-1.aws.neon.tech"
    assert make_url(settings.migration_database_url).drivername == "postgresql+psycopg"


def test_neon_application_url_must_be_pooled() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://app_user:example-password@ep-prod.ap-southeast-1.aws.neon.tech/pulseops",
        )


def test_neon_migration_url_must_be_direct() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://app_user:example-password@ep-prod-pooler.ap-southeast-1.aws.neon.tech/pulseops",
            migration_database_url="postgresql://migration_user:example-password@ep-prod-pooler.ap-southeast-1.aws.neon.tech/pulseops",
        )


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer"])
def test_neon_urls_reject_tls_downgrade_modes(sslmode: str) -> None:
    with pytest.raises(ValidationError, match="sslmode"):
        Settings(
            _env_file=None,
            database_url=f"postgresql://app_user:example-password@ep-prod-pooler.ap-southeast-1.aws.neon.tech/pulseops?sslmode={sslmode}",
        )


def test_local_database_url_and_explicit_cors_origins_are_supported() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://pulseops:local-password@localhost:5432/pulseops",
        cors_origins="http://localhost:5173, https://pulseops.example.com/",
    )

    assert settings.cors_origin_list == ["http://localhost:5173", "https://pulseops.example.com"]


@pytest.mark.parametrize("origins", ["*", "https://*.vercel.app", "https://pulseops.example.com/path"])
def test_cors_rejects_wildcards_and_non_origin_urls(origins: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://pulseops:local-password@localhost/pulseops", cors_origins=origins)


def test_production_requires_signing_secret_and_https_cors() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, database_url="postgresql://pulseops@localhost/pulseops", app_env="production", cors_origins="https://pulseops.example.com")
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(_env_file=None, database_url="postgresql://pulseops@localhost/pulseops", app_env="production", jwt_secret_key="x" * 48, cors_origins="http://pulseops.example.com")


def test_production_defaults_to_read_only_without_worker() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://pulseops@localhost/pulseops", app_env="production", jwt_secret_key="x" * 48, cors_origins="https://pulseops.example.com")
    assert settings.service_mutations_enabled is False
    assert settings.monitoring_worker_enabled is False


def test_local_development_keeps_service_management_and_worker_enabled() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://pulseops@localhost/pulseops", app_env="development")
    assert settings.service_mutations_enabled is True
    assert settings.monitoring_worker_enabled is True


def test_worker_environment_is_disabled_until_explicitly_enabled() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://pulseops@localhost/pulseops", app_env="worker")
    assert settings.service_mutations_enabled is False
    assert settings.monitoring_worker_enabled is False
