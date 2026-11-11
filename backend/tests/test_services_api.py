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
    }
    payload.update(overrides)
    return payload


def get_user(test_db: sessionmaker, user_id: UUID) -> User:
    with test_db() as db:
        return db.get(User, user_id)


def test_service_crud_endpoints(test_db: sessionmaker, service_api_user: UUID) -> None:
    with test_db() as db:
        user = db.get(User, service_api_user)
        created = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db, user)
        service_id = created.id
        assert ServiceRead.model_validate(created).name == "Payments API"

        listed = list_services(db, user)
        assert any(service.id == service_id for service in listed)
        assert get_service(service_id, db, user).target == "https://payments.example.test/health"

        updated = update_service(service_id, ServiceUpdate.model_validate({"name": "Payments production API", "description": None}), db, user)
        assert updated.name == "Payments production API"
        assert updated.description is None

        deleted = delete_service(service_id, db, user)
        assert deleted.status_code == 204
        with pytest.raises(HTTPException) as error:
            get_service(service_id, db, user)
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

    if "created_by" in overrides:
        with pytest.raises(ValidationError):
            ServiceCreate.model_validate(create_payload(service_api_user, **overrides))
    else:
        with pytest.raises(ValidationError):
            ServiceCreate.model_validate(create_payload(service_api_user, **overrides))


def test_client_cannot_choose_service_owner(service_api_user: UUID) -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ServiceCreate.model_validate(create_payload(service_api_user, created_by=str(uuid4())))


def test_service_records_are_isolated_by_owner(test_db: sessionmaker, service_api_user: UUID) -> None:
    other_user_id = uuid4()
    with test_db.begin() as db:
        db.add(User(id=other_user_id, email="other-owner@example.test", display_name="Other", password_hash="$argon2id$fixture"))
    with test_db() as db:
        owner = db.get(User, service_api_user)
        other = db.get(User, other_user_id)
        service = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db, owner)
        assert service.created_by == owner.id
        assert list_services(db, other) == []
        for action in (
            lambda: get_service(service.id, db, other),
            lambda: update_service(service.id, ServiceUpdate.model_validate({"name": "Hijacked"}), db, other),
            lambda: delete_service(service.id, db, other),
        ):
            with pytest.raises(HTTPException) as error:
                action()
            assert error.value.status_code == 404


def test_service_mutations_can_be_disabled_for_public_deployment(monkeypatch, service_api_user: UUID) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "service_mutations_enabled", False)
    user = User(id=service_api_user, email="readonly@example.test", display_name="Readonly", password_hash="hash")
    operations = (
        lambda: create_service(ServiceCreate.model_validate(create_payload(service_api_user)), None, user),
        lambda: update_service(uuid4(), ServiceUpdate.model_validate({"is_enabled": False}), None, user),
        lambda: delete_service(uuid4(), None, user),
    )
    for operation in operations:
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 503


def test_patch_validates_updates(test_db: sessionmaker, service_api_user: UUID) -> None:
    from pydantic import ValidationError

    with test_db() as db:
        user = db.get(User, service_api_user)
        service = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db, user)
        for invalid in ({"name": " "}, {"name": None}, {"check_interval_seconds": 0}):
            with pytest.raises(ValidationError):
                ServiceUpdate.model_validate(invalid)
        with pytest.raises(HTTPException) as error:
            update_service(uuid4(), ServiceUpdate.model_validate({"name": "Missing"}), db, user)
    assert error.value.status_code == 404


@pytest.mark.parametrize("operation", ["get", "patch", "delete"])
def test_missing_service_returns_404(test_db: sessionmaker, operation: str) -> None:
    with test_db() as db, pytest.raises(HTTPException) as error:
        missing_id = uuid4()
        if operation == "get":
            get_service(missing_id, db, User(id=uuid4(), email="missing@example.test", display_name="Missing", password_hash="x"))
        elif operation == "patch":
            update_service(missing_id, ServiceUpdate.model_validate({"name": "Missing"}), db, User(id=uuid4(), email="missing@example.test", display_name="Missing", password_hash="x"))
        else:
            delete_service(missing_id, db, User(id=uuid4(), email="missing@example.test", display_name="Missing", password_hash="x"))
    assert error.value.status_code == 404
    assert error.value.detail == "Monitored service not found"


def test_service_with_incident_history_cannot_be_deleted(test_db: sessionmaker, service_api_user: UUID) -> None:
    with test_db() as db:
        service = create_service(ServiceCreate.model_validate(create_payload(service_api_user)), db, db.get(User, service_api_user))
        service_id = service.id
        db.add(Incident(service_id=service_id, title="Historical incident"))
        db.commit()

    with test_db() as db, pytest.raises(HTTPException) as error:
        delete_service(service_id, db, db.get(User, service_api_user))
    assert error.value.status_code == 409
    assert error.value.detail == "This service has check or incident history and cannot be deleted"
