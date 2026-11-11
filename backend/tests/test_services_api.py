from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.services import create_service, delete_service, get_service, list_services, update_service
from app.models import Incident, MonitoredService, User
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate


@pytest.fixture
def test_db() -> Generator[sessionmaker, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
        connection.execute("PRAGMA foreign_keys=ON")

    # incident_events uses PostgreSQL JSONB and is not needed by these service routes.
    User.__table__.create(engine)
    MonitoredService.__table__.create(engine)
    Incident.__table__.create(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture
def service_api_user(test_db: sessionmaker) -> UUID:
    user_id = uuid4()
    with test_db.begin() as db:
        db.add(
            User(
                id=user_id,
                email=f"service-api-{user_id}@example.test",
                display_name="Service API test",
                password_hash="$argon2id$test-fixture-hash",
            )
        )
    return user_id


def create_payload(user_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Payments API",
        "description": "Primary payments endpoint",
        "check_type": "http",
        "target": "https://payments.example.test/health",
        "check_interval_seconds": 30,
        "timeout_seconds": 5,
        "expected_status_code": 200,
        "is_enabled": True,
        "created_by": str(user_id),
    }
    payload.update(overrides)
    return payload


def test_service_crud_endpoints(test_db: sessionmaker, service_api_user: UUID) -> None:
    with test_db() as db:
        created = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db)
        service_id = created.id
        assert ServiceRead.model_validate(created).name == "Payments API"

        listed = list_services(db)
        assert any(service.id == service_id for service in listed)
        assert get_service(service_id, db).target == "https://payments.example.test/health"

        updated = update_service(service_id, ServiceUpdate.model_validate({"name": "Payments production API", "description": None}), db)
        assert updated.name == "Payments production API"
        assert updated.description is None

        deleted = delete_service(service_id, db)
        assert deleted.status_code == 204
        with pytest.raises(HTTPException) as error:
            get_service(service_id, db)
        assert error.value.status_code == 404
        assert error.value.detail == "Monitored service not found"


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"check_type": "icmp"},
        {"check_interval_seconds": 0},
        {"timeout_seconds": -1},
        {"expected_status_code": 99},
        {"check_type": "tcp", "expected_status_code": 200},
        {"unexpected": True},
    ],
)
def test_create_rejects_invalid_data(service_api_user: UUID, overrides: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ServiceCreate.model_validate(create_payload(service_api_user, **overrides))


def test_create_requires_existing_creator(test_db: sessionmaker) -> None:
    with test_db() as db, pytest.raises(HTTPException) as error:
        create_service(ServiceCreate.model_validate(create_payload(uuid4())), db)
    assert error.value.status_code == 422
    assert error.value.detail == "created_by must reference an existing user"


def test_patch_validates_updates(test_db: sessionmaker, service_api_user: UUID) -> None:
    from pydantic import ValidationError

    with test_db() as db:
        service = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db)
        for invalid in ({"name": " "}, {"name": None}, {"check_interval_seconds": 0}):
            with pytest.raises(ValidationError):
                ServiceUpdate.model_validate(invalid)
        with pytest.raises(HTTPException) as error:
            update_service(uuid4(), ServiceUpdate.model_validate({"name": "Missing"}), db)
    assert error.value.status_code == 404


@pytest.mark.parametrize("operation", ["get", "patch", "delete"])
def test_missing_service_returns_404(test_db: sessionmaker, operation: str) -> None:
    with test_db() as db, pytest.raises(HTTPException) as error:
        missing_id = uuid4()
        if operation == "get":
            get_service(missing_id, db)
        elif operation == "patch":
            update_service(missing_id, ServiceUpdate.model_validate({"name": "Missing"}), db)
        else:
            delete_service(missing_id, db)
    assert error.value.status_code == 404
    assert error.value.detail == "Monitored service not found"


def test_service_with_incident_history_cannot_be_deleted(test_db: sessionmaker, service_api_user: UUID) -> None:
    with test_db() as db:
        service = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db)
        service_id = service.id
        db.add(Incident(service_id=service_id, title="Historical incident"))
        db.commit()

    with test_db() as db, pytest.raises(HTTPException) as error:
        delete_service(service_id, db)
    assert error.value.status_code == 409
    assert error.value.detail == "This service has check or incident history and cannot be deleted"
