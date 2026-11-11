"""Create one local development user without exposing password material."""

import getpass
import os
import sys
from collections.abc import Callable
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import User

LOOPBACK_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


def ensure_local_database(database_url: str) -> None:
    """Refuse to run this development helper against a non-local database."""
    host = make_url(database_url).host
    if host is None or host.strip("[]").lower() not in LOOPBACK_DATABASE_HOSTS:
        raise ValueError("Refusing to create a development user: DATABASE_URL must point to localhost")


def _validated_email(value: str) -> str:
    email = value.strip().lower()
    local_part, separator, domain = email.partition("@")
    if (
        len(email) > 320
        or not separator
        or not local_part
        or not domain
        or "@" in domain
        or any(char.isspace() for char in email)
    ):
        raise ValueError("Enter a valid development email address (maximum 320 characters)")
    return email


def _validated_display_name(value: str) -> str:
    display_name = value.strip()
    if not display_name or len(display_name) > 120:
        raise ValueError("Display name must contain 1 to 120 characters")
    return display_name


def _validated_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Development password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value) > MAX_PASSWORD_LENGTH or not value.strip():
        raise ValueError(f"Development password must be non-empty and no longer than {MAX_PASSWORD_LENGTH} characters")
    return value


def create_dev_user(
    email: str,
    display_name: str,
    password: str,
    session_factory: sessionmaker[Session] = SessionLocal,
    password_hasher: PasswordHash | None = None,
) -> tuple[UUID, bool]:
    """Create a user once; return its ID and whether this call created it."""
    normalized_email = _validated_email(email)
    normalized_name = _validated_display_name(display_name)
    validated_password = _validated_password(password)

    with session_factory() as db:
        existing = db.scalar(select(User).where(User.email == normalized_email))
        if existing is not None:
            return existing.id, False

        hasher = password_hasher or PasswordHash.recommended()
        user = User(
            email=normalized_email,
            display_name=normalized_name,
            password_hash=hasher.hash(validated_password),
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Another CLI invocation may have inserted the same email after our read.
            db.rollback()
            existing = db.scalar(select(User).where(User.email == normalized_email))
            if existing is None:
                raise
            return existing.id, False
        db.refresh(user)
        return user.id, True


def _read_value(
    env_name: str,
    prompt: str,
    input_fn: Callable[[str], str],
) -> str:
    value = os.environ.get(env_name)
    return input_fn(prompt) if value is None else value


def _read_password() -> str:
    password = os.environ.get("PULSEOPS_DEV_USER_PASSWORD")
    if password is not None:
        return password

    password = getpass.getpass("Development password (input hidden): ")
    confirmation = getpass.getpass("Confirm development password: ")
    if password != confirmation:
        raise ValueError("Passwords did not match")
    return password


def main() -> int:
    try:
        ensure_local_database(settings.database_url)
        email = _read_value("PULSEOPS_DEV_USER_EMAIL", "Development email: ", input)
        display_name = _read_value("PULSEOPS_DEV_USER_DISPLAY_NAME", "Display name: ", input)
        password = _read_password()
        user_id, created = create_dev_user(email, display_name, password)
    except ValueError as exc:
        print(f"Cannot create development user: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Cannot create development user: check local PostgreSQL and confirm migrations are applied.", file=sys.stderr)
        return 1

    if created:
        print(f"Created development user UUID: {user_id}")
    else:
        print(f"Email already exists; user and password were left unchanged. UUID: {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
