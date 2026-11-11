from collections.abc import Generator

import pytest
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli.create_dev_user import _read_password, create_dev_user
from app.models import User


@pytest.fixture
def user_sessions() -> Generator[sessionmaker[Session], None, None]:
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
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


def test_creates_user_with_argon2_hash(user_sessions: sessionmaker[Session]) -> None:
    raw_password = "correct horse battery staple"
    user_id, created = create_dev_user(
        "  Dev.User@Example.Test ",
        "Local Developer",
        raw_password,
        session_factory=user_sessions,
    )

    assert created is True
    with user_sessions() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.email == "dev.user@example.test"
        assert user.display_name == "Local Developer"
        assert user.password_hash != raw_password
        assert user.password_hash.startswith("$argon2id$")
        assert PasswordHash.recommended().verify(raw_password, user.password_hash)


def test_duplicate_email_is_idempotent_and_does_not_change_password(user_sessions: sessionmaker[Session]) -> None:
    first_id, first_created = create_dev_user(
        "dev@example.test", "First Name", "correct horse battery staple", session_factory=user_sessions
    )
    with user_sessions() as db:
        original_hash = db.get(User, first_id).password_hash

    second_id, second_created = create_dev_user(
        " DEV@example.test ", "Different Name", "a different long password", session_factory=user_sessions
    )

    assert first_created is True
    assert second_created is False
    assert second_id == first_id
    with user_sessions() as db:
        user = db.scalar(select(User).where(User.email == "dev@example.test"))
        assert user is not None
        assert user.display_name == "First Name"
        assert user.password_hash == original_hash


def test_rejects_non_local_database_url() -> None:
    from app.cli.create_dev_user import ensure_local_database

    with pytest.raises(ValueError, match="localhost"):
        ensure_local_database("postgresql+psycopg://user:password@example.com/pulseops")


def test_interactive_password_is_hidden_and_confirmed(monkeypatch) -> None:
    monkeypatch.delenv("PULSEOPS_DEV_USER_PASSWORD", raising=False)
    answers = iter(["correct horse battery staple", "correct horse battery staple"])
    prompts = []

    def hidden_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("app.cli.create_dev_user.getpass.getpass", hidden_prompt)
    assert _read_password() == "correct horse battery staple"
    assert len(prompts) == 2
    assert all("hidden" in prompt.lower() or "confirm" in prompt.lower() for prompt in prompts)
