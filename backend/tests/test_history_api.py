from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.history import list_incident_events, list_incidents, list_service_checks
from app.models import Incident, MonitoredService, ServiceCheck, User


@pytest.fixture
def history_sessions() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
        connection.execute("PRAGMA foreign_keys=ON")

    User.__table__.create(engine)
    MonitoredService.__table__.create(engine)
    ServiceCheck.__table__.create(engine)
    Incident.__table__.create(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


def test_monitoring_history_and_incidents_are_scoped_to_service_owner(history_sessions) -> None:
    first_id, second_id = uuid4(), uuid4()
    with history_sessions.begin() as db:
        first = User(id=first_id, email="first@example.test", display_name="First", password_hash="hash")
        second = User(id=second_id, email="second@example.test", display_name="Second", password_hash="hash")
        db.add_all([first, second])
        db.flush()
        first_service = MonitoredService(
            name="First service", target="https://first.example.test/health", created_by=first_id
        )
        second_service = MonitoredService(
            name="Second service", target="https://second.example.test/health", created_by=second_id
        )
        db.add_all([first_service, second_service])
        db.flush()
        first_check = ServiceCheck(service_id=first_service.id, is_available=True, response_time_ms=12, status_code=200)
        second_check = ServiceCheck(service_id=second_service.id, is_available=True, response_time_ms=19, status_code=200)
        first_incident = Incident(service_id=first_service.id, title="First incident")
        second_incident = Incident(service_id=second_service.id, title="Second incident")
        db.add_all([first_check, second_check, first_incident, second_incident])
        db.flush()
        second_service_id = second_service.id
        second_incident_id = second_incident.id
        first_incident_id = first_incident.id

    with history_sessions() as db:
        first_user = db.get(User, first_id)
        visible_incidents = list_incidents(None, 100, db, first_user)
        assert [incident.id for incident in visible_incidents] == [first_incident_id]

        with pytest.raises(HTTPException) as check_error:
            list_service_checks(second_service_id, 48, db, first_user)
        assert check_error.value.status_code == 404

        with pytest.raises(HTTPException) as event_error:
            list_incident_events(second_incident_id, 200, db, first_user)
        assert event_error.value.status_code == 404
