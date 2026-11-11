"""Provision a PulseOps account from a trusted operator shell; there is no public signup route."""

import getpass
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.cli.create_dev_user import _read_value, create_dev_user


def main() -> int:
    try:
        email = _read_value("PULSEOPS_USER_EMAIL", "User email: ", input)
        display_name = _read_value("PULSEOPS_USER_DISPLAY_NAME", "Display name: ", input)
        password = getpass.getpass("Password (input hidden): ")
        if password != getpass.getpass("Confirm password: "):
            raise ValueError("Passwords did not match")
        user_id, created = create_dev_user(email, display_name, password)
    except ValueError as exc:
        print(f"Cannot create user: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Cannot create user: verify DATABASE_URL and that migrations have been applied.", file=sys.stderr)
        return 1
    if created:
        print(f"Created user UUID: {user_id}")
    else:
        print(f"Email already exists; account and password were left unchanged. UUID: {user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
