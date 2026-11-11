from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4

from app.core.database import engine
from app.models import Incident, IncidentEvent, MonitoredService, User


def _create_service(session: Session, suffix: str = "") -> tuple[User, MonitoredService]:
    user = User(email=f"Owner{suffix}@Example.com", display_name="Owner", password_hash="$argon2id$test-hash")
    session.add(user)
    session.flush()
    service = MonitoredService(name=f"API{suffix}", target="https://example.com/health", creator=user)
    session.add(service)
    session.flush()
    return user, service


def test_migration_creates_all_application_tables() -> None:
    table_names = set(inspect(engine).get_table_names())
    assert {"users", "monitored_services", "incidents", "incident_events", "service_checks"} <= table_names


def test_email_is_normalized_and_unique() -> None:
    with Session(engine) as session, session.begin():
        first = User(email="  PulseOps@Example.COM ", display_name="One", password_hash="$argon2id$one")
        session.add(first)
        session.flush()
        assert first.email == "pulseops@example.com"

    try:
        with Session(engine) as session, session.begin():
            session.add(User(email="PULSEOPS@example.com", display_name="Two", password_hash="$argon2id$two"))
            session.flush()
    except IntegrityError:
        pass
    else:
        raise AssertionError("case-insensitive duplicate email was accepted")

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE email = 'pulseops@example.com'"))


def test_only_one_active_incident_per_service_and_history_is_retained() -> None:
    suffix = uuid4().hex
    with Session(engine) as session, session.begin():
        user, service = _create_service(session, suffix)
        incident = Incident(service=service, title="Unavailable", severity="high")
        session.add(incident)
        session.flush()
        session.add(IncidentEvent(incident=incident, actor=user, event_type="created", payload={"source": "test"}))
        session.flush()
        incident_id = incident.id
        service_id = service.id
        user_id = user.id

    try:
        with Session(engine) as session, session.begin():
            session.add(Incident(service_id=service_id, title="Still unavailable", status="acknowledged"))
            session.flush()
    except IntegrityError:
        pass
    else:
        raise AssertionError("a second active incident for the service was accepted")

    with Session(engine) as session, session.begin():
        incident = session.get(Incident, incident_id)
        assert incident is not None
        incident.status = "resolved"
        session.flush()
        session.add(Incident(service_id=service_id, title="Recovered then failed again"))

    with Session(engine) as session:
        assert session.query(IncidentEvent).filter_by(incident_id=incident_id).count() == 1
        assert session.get(User, user_id) is not None
        assert session.query(Incident).filter_by(service_id=service_id).count() == 2

    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
    except IntegrityError:
        pass
    else:
        raise AssertionError("an incident with timeline events was deleted")

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM incident_events WHERE incident_id IN (SELECT id FROM incidents WHERE service_id = :id)"),
            {"id": service_id},
        )
        connection.execute(text("DELETE FROM incidents WHERE service_id = :id"), {"id": service_id})
        connection.execute(text("DELETE FROM monitored_services WHERE id = :id"), {"id": service_id})
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_schema_uses_timezone_aware_timestamps_and_hash_only_credential_field() -> None:
    inspector = inspect(engine)
    user_columns = {column["name"]: column["type"] for column in inspector.get_columns("users")}
    assert "password_hash" in user_columns
    assert "password" not in user_columns
    assert user_columns["created_at"].timezone is True
    assert inspect(engine).get_foreign_keys("incident_events")
