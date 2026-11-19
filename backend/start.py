"""Migrate the database, then supervise FastAPI and the optional monitor worker."""

import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence


BACKEND_ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("pulseops.startup")
WORKER_RESTART_INITIAL_SECONDS = 1.0
WORKER_RESTART_MAX_SECONDS = 30.0
WORKER_STABLE_SECONDS = 60.0
CHILD_STOP_TIMEOUT_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 0.25


def _port_from_environment() -> str:
    port = os.environ.get("PORT", "8000")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


def _stop_process(process: subprocess.Popen[bytes] | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    logger.info("Stopping %s child process", name)
    process.terminate()
    try:
        process.wait(timeout=CHILD_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.error("%s did not stop within %.1f seconds; killing it", name, CHILD_STOP_TIMEOUT_SECONDS)
        process.kill()
        process.wait()


def supervise_processes(
    api_command: Sequence[str],
    worker_command: Sequence[str] | None,
    *,
    popen_factory: Callable[..., subprocess.Popen[bytes]] | None = None,
    stop_event: threading.Event | None = None,
    install_signal_handlers: bool = True,
) -> int:
    """Keep the API foregrounded and restart a failed worker with bounded backoff."""
    spawn = popen_factory or subprocess.Popen
    shutdown = stop_event or threading.Event()
    previous_handlers: dict[signal.Signals, object] = {}

    if install_signal_handlers:
        def request_shutdown(signum: int, _frame: object) -> None:
            logger.info("Received signal %s; shutting down child processes", signum)
            shutdown.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, request_shutdown)

    api_process: subprocess.Popen[bytes] | None = None
    worker_process: subprocess.Popen[bytes] | None = None
    worker_started_at: float | None = None
    restart_delay = WORKER_RESTART_INITIAL_SECONDS
    next_worker_start = time.monotonic()

    try:
        api_process = spawn(list(api_command), cwd=BACKEND_ROOT)
        while not shutdown.is_set():
            api_exit_code = api_process.poll()
            if api_exit_code is not None:
                return api_exit_code

            if worker_command is not None:
                if worker_process is not None:
                    worker_exit_code = worker_process.poll()
                    if worker_exit_code is not None:
                        runtime = time.monotonic() - (
                            worker_started_at if worker_started_at is not None else time.monotonic()
                        )
                        if runtime >= WORKER_STABLE_SECONDS:
                            restart_delay = WORKER_RESTART_INITIAL_SECONDS
                        logger.error(
                            "Monitoring worker exited unexpectedly (exit_code=%s); restarting in %.1f seconds",
                            worker_exit_code,
                            restart_delay,
                        )
                        worker_process = None
                        worker_started_at = None
                        next_worker_start = time.monotonic() + restart_delay
                        restart_delay = min(restart_delay * 2, WORKER_RESTART_MAX_SECONDS)

                if worker_process is None and time.monotonic() >= next_worker_start:
                    try:
                        worker_process = spawn(list(worker_command), cwd=BACKEND_ROOT)
                        worker_started_at = time.monotonic()
                        logger.info("Started monitoring worker child process")
                    except OSError:
                        logger.exception("Could not start monitoring worker; retrying in %.1f seconds", restart_delay)
                        next_worker_start = time.monotonic() + restart_delay
                        restart_delay = min(restart_delay * 2, WORKER_RESTART_MAX_SECONDS)

            shutdown.wait(POLL_INTERVAL_SECONDS)
        return 0
    finally:
        _stop_process(worker_process, "monitoring worker")
        _stop_process(api_process, "FastAPI")
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main() -> int:
    try:
        port = _port_from_environment()
    except ValueError as exc:
        print(f"Cannot start PulseOps API: {exc}", file=sys.stderr)
        return 2

    try:
        from app.core.config import Settings

        runtime_settings = Settings()
    except Exception:
        print("Cannot start PulseOps: required application settings are invalid.", file=sys.stderr)
        return 2

    worker_enabled = bool(runtime_settings.monitoring_worker_enabled)
    if worker_enabled and not runtime_settings.worker_lock_database_url:
        print(
            "Cannot start PulseOps: WORKER_LOCK_DATABASE_URL is required when "
            "MONITORING_WORKER_ENABLED=true.",
            file=sys.stderr,
        )
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
    worker_command = [sys.executable, "-m", "app.monitoring.worker"] if worker_enabled else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return supervise_processes(server_command, worker_command)


if __name__ == "__main__":
    raise SystemExit(main())
