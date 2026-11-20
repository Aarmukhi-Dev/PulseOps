from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import LoginRequest, RegisterRequest, login, register
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
    for path in ("/api/services", "/api/services/{service_id}", "/api/incidents", "/api/incidents/{incident_id}/events", "/api/v1/metrics/current", "/api/auth/me"):
        operations = paths[path]
        operation = next(iter(operations.values()))
        assert operation["security"] == [{"HTTPBearer": []}]
    registration = paths["/api/auth/register"]["post"]
    assert "security" not in registration
    assert "201" in registration["responses"]


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


def valid_registration(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": "  Pulse User  ",
        "email": " New.User@Example.Test ",
        "password": "a strong test password 123",
        "password_confirmation": "a strong test password 123",
    }
    payload.update(overrides)
    return payload


def test_register_creates_normalized_user_hash_and_bearer_token(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions() as db:
        response = register(RegisterRequest.model_validate(valid_registration()), db)
        stored = db.query(User).filter_by(email=response.user.email).one_or_none()

        assert response.token_type == "bearer"
        assert response.user.email == "new.user@example.test"
        assert response.user.display_name == "Pulse User"
        assert _decode_access_token(response.access_token).hex
        assert stored is not None
        assert stored.password_hash != "a strong test password 123"
        assert stored.password_hash.startswith("$argon2id$")
        assert PasswordHash.recommended().verify("a strong test password 123", stored.password_hash)
        assert not hasattr(stored, "role")
        assert authenticate_user(response.user.email, "a strong test password 123", db) is not None
        assert get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=response.access_token), db
        ).id == stored.id
        assert set(response.model_dump()) == {"access_token", "token_type", "user"}


def test_registration_normalizes_email_case_and_whitespace() -> None:
    payload = RegisterRequest.model_validate(valid_registration(email="Person@BÜCHER.example"))
    assert payload.email == "person@bücher.example"


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"email": "person@-bad.example"},
        {"email": "person@example"},
        {"password": "short", "password_confirmation": "short"},
        {"password": "            ", "password_confirmation": "            "},
        {"password_confirmation": "a different long password 123"},
        {"display_name": "  "},
        {"unexpected": "field"},
    ],
)
def test_registration_rejects_invalid_input(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate(valid_registration(**overrides))


def test_password_mismatch_validation_does_not_echo_submitted_secret() -> None:
    with pytest.raises(ValidationError) as error:
        RegisterRequest.model_validate(valid_registration(password_confirmation="different secret phrase 123"))
    assert "a strong test password 123" not in str(error.value)
    assert "different secret phrase 123" not in str(error.value)


def test_registration_rejects_duplicate_email_without_changing_account(auth_sessions: sessionmaker[Session]) -> None:
    with auth_sessions() as db:
        existing = db.query(User).filter_by(email="auth@example.test").one()
        password_hash = existing.password_hash
        with pytest.raises(HTTPException) as error:
            register(
                RegisterRequest.model_validate(valid_registration(email=" AUTH@example.test ")),
                db,
            )
        assert error.value.status_code == 409
        assert db.query(User).filter_by(email="auth@example.test").one().password_hash == password_hash


def test_registration_handles_unique_email_race_safely() -> None:
    existing = User(email="race@example.test", display_name="Existing", password_hash="$argon2id$existing")

    class RaceSession:
        def __init__(self) -> None:
            self.lookups = 0

        def scalar(self, _statement):
            self.lookups += 1
            return None if self.lookups == 1 else existing

        def add(self, _user) -> None:
            pass

        def commit(self) -> None:
            raise IntegrityError("insert", {}, Exception("unique violation"))

        def rollback(self) -> None:
            pass

    with pytest.raises(HTTPException) as error:
        register(RegisterRequest.model_validate(valid_registration(email="race@example.test")), RaceSession())
    assert error.value.status_code == 409
    assert error.value.detail == "An account with this email already exists"
