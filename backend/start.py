"""Run database migrations, then start the PulseOps FastAPI server."""

import os
from pathlib import Path
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parent


def _port_from_environment() -> str:
    port = os.environ.get("PORT", "8000")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


def main() -> int:
    try:
        port = _port_from_environment()
    except ValueError as exc:
        print(f"Cannot start PulseOps API: {exc}", file=sys.stderr)
        return 2

    migration_command = [sys.executable, "-m", "alembic", "upgrade", "head"]
    try:
        subprocess.run(migration_command, cwd=BACKEND_ROOT, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("Database migration failed; refusing to start the PulseOps API.", file=sys.stderr)
        return 1

    server_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    os.execv(sys.executable, server_command)
    return 0  # pragma: no cover - execv replaces the current process.


if __name__ == "__main__":
    raise SystemExit(main())
