from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import LoginRequest, login
from app.core.auth import _decode_access_token, authenticate_user, create_access_token, get_current_user
from app.models import User


@pytest.fixture
def auth_sessions() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

    User.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory.begin() as db:
        db.add(User(email="auth@example.test", display_name="Auth User", password_hash=PasswordHash.recommended().hash("long test password")))
    yield factory
    engine.dispose()


def test_login_normalizes_email_and_returns_signed_bearer(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions() as db:
        result = login(LoginRequest(email=" AUTH@Example.Test ", password="long test password"), db)
        assert result.token_type == "bearer"
        assert result.user.email == "auth@example.test"
        assert _decode_access_token(result.access_token).hex
        current = get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=result.access_token), db)
        assert current.email == result.user.email


@pytest.mark.parametrize("email,password", [("auth@example.test", "wrong password"), ("unknown@example.test", "wrong password")])
def test_login_failure_is_generic(auth_sessions: sessionmaker[Session], email: str, password: str) -> None:
    with auth_sessions() as db:
        with pytest.raises(HTTPException) as error:
            login(LoginRequest(email=email, password=password), db)
    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"


def test_invalid_or_tampered_token_is_rejected(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions() as db:
        for token in ("bad.token.value", create_access_token(uuid4()) + "x"):
            with pytest.raises(HTTPException) as error:
                get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
            assert error.value.status_code == 401


def test_missing_bearer_credentials_are_rejected(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions() as db:
        with pytest.raises(HTTPException) as error:
            get_current_user(None, db)
    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"


def test_data_routes_declare_bearer_security() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for path in ("/api/services", "/api/services/{service_id}", "/api/incidents", "/api/incidents/{incident_id}/events", "/api/v1/metrics/current"):
        operations = paths[path]
        operation = next(iter(operations.values()))
        assert operation["security"] == [{"HTTPBearer": []}]


def test_inactive_users_cannot_authenticate(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions.begin() as db:
        user = db.query(User).filter_by(email="auth@example.test").one()
        user.is_active = False
        user_id = user.id
        password_hash = user.password_hash
    with auth_sessions() as db:
        assert authenticate_user("auth@example.test", "long test password", db) is None
        token = create_access_token(user_id)
        with pytest.raises(HTTPException):
            get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)


def test_malformed_stored_hash_fails_as_invalid_credentials(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions.begin() as db:
        user = db.query(User).filter_by(email="auth@example.test").one()
        user.password_hash = "not-a-valid-password-hash"
    with auth_sessions() as db:
        assert authenticate_user("auth@example.test", "any password", db) is None
