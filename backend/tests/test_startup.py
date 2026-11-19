import logging
import signal
import subprocess
import sys
import threading
from pathlib import Path

import start


class FakeProcess:
    def __init__(self, polls: list[int | None] | None = None) -> None:
        self.polls = list(polls or [None])
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        if self.polls:
            value = self.polls.pop(0)
            if value is not None:
                self.returncode = value
            return value
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -getattr(signal, "SIGTERM", 15)

    def kill(self) -> None:
        self.killed = True
        self.returncode = -getattr(signal, "SIGKILL", 9)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_start_runs_migrations_before_starting_api_and_worker(monkeypatch) -> None:
    events: list[object] = []
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("MONITORING_WORKER_ENABLED", "true")
    monkeypatch.setenv("WORKER_LOCK_DATABASE_URL", "postgresql://direct.invalid/db")
    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda command, **kwargs: events.append((command, kwargs)),
    )

    def fake_supervise(api_command, worker_command):
        events.append((list(api_command), list(worker_command)))
        return 0

    monkeypatch.setattr(start, "supervise_processes", fake_supervise)
    assert start.main() == 0

    assert events[0] == (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        {"cwd": Path(start.__file__).resolve().parent, "check": True},
    )
    assert events[1] == (
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8123"],
        [sys.executable, "-m", "app.monitoring.worker"],
    )


def test_worker_is_not_started_when_disabled(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("MONITORING_WORKER_ENABLED", "false")
    monkeypatch.delenv("WORKER_LOCK_DATABASE_URL", raising=False)
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(start, "supervise_processes", lambda api, worker: calls.append((api, worker)) or 0)

    assert start.main() == 0
    assert calls[0][1] is None


def test_worker_enabled_requires_lock_url_before_migrations(monkeypatch, capsys) -> None:
    migration_calls: list[bool] = []
    monkeypatch.setenv("MONITORING_WORKER_ENABLED", "true")
    monkeypatch.delenv("WORKER_LOCK_DATABASE_URL", raising=False)
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: migration_calls.append(True))

    assert start.main() == 2
    assert not migration_calls
    assert "WORKER_LOCK_DATABASE_URL" in capsys.readouterr().err


def test_start_refuses_to_start_processes_if_migration_fails(monkeypatch, capsys) -> None:
    monkeypatch.setenv("MONITORING_WORKER_ENABLED", "false")
    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, args[0])),
    )
    starts: list[bool] = []
    monkeypatch.setattr(start, "supervise_processes", lambda *args: starts.append(True))

    assert start.main() == 1
    assert not starts
    assert "migration failed" in capsys.readouterr().err.lower()


def test_start_rejects_invalid_port_before_running_migrations(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "not-a-port")
    calls: list[bool] = []
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: calls.append(True))

    assert start.main() == 2
    assert not calls


def test_supervisor_starts_worker_and_stops_it_when_api_exits(monkeypatch) -> None:
    api = FakeProcess([None, 0])
    worker = FakeProcess()
    spawned: list[tuple[list[str], FakeProcess]] = []

    def spawn(command, **kwargs):
        process = api if command[2] == "uvicorn" else worker
        spawned.append((command, process))
        return process

    monkeypatch.setattr(start, "POLL_INTERVAL_SECONDS", 0.001)
    code = start.supervise_processes(
        [sys.executable, "-m", "uvicorn"],
        [sys.executable, "-m", "app.monitoring.worker"],
        popen_factory=spawn,
        install_signal_handlers=False,
    )

    assert code == 0
    assert [entry[0][2] for entry in spawned] == ["uvicorn", "app.monitoring.worker"]
    assert worker.terminated


def test_supervisor_restarts_failed_worker_with_backoff(monkeypatch, caplog) -> None:
    api = FakeProcess([None, None, 0])
    first_worker = FakeProcess([7])
    second_worker = FakeProcess()
    workers = iter([first_worker, second_worker])
    started_workers = []

    def spawn(command, **kwargs):
        if command[2] == "uvicorn":
            return api
        process = next(workers)
        started_workers.append(process)
        return process

    monkeypatch.setattr(start, "WORKER_RESTART_INITIAL_SECONDS", 0)
    monkeypatch.setattr(start, "POLL_INTERVAL_SECONDS", 0)
    with caplog.at_level(logging.ERROR, logger="pulseops.startup"):
        assert start.supervise_processes(
            [sys.executable, "-m", "uvicorn"],
            [sys.executable, "-m", "app.monitoring.worker"],
            popen_factory=spawn,
            install_signal_handlers=False,
        ) == 0

    assert len(started_workers) == 2
    assert second_worker.terminated
    assert "Monitoring worker exited unexpectedly" in caplog.text


def test_supervisor_forwards_sigterm_and_stops_both_children(monkeypatch) -> None:
    handlers = {}
    event = threading.Event()
    api = FakeProcess()
    worker = FakeProcess()

    def fake_signal(signum, handler):
        old = handlers.get(signum, signal.SIG_DFL)
        handlers[signum] = handler
        return old

    def spawn(command, **kwargs):
        if command[2] == "app.monitoring.worker":
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return worker
        return api

    monkeypatch.setattr(start.signal, "signal", fake_signal)
    monkeypatch.setattr(start, "POLL_INTERVAL_SECONDS", 0)
    assert start.supervise_processes(
        [sys.executable, "-m", "uvicorn"],
        [sys.executable, "-m", "app.monitoring.worker"],
        popen_factory=spawn,
        stop_event=event,
    ) == 0
    assert event.is_set()
    assert worker.terminated
    assert api.terminated


def test_supervisor_kills_child_that_ignores_terminate(monkeypatch) -> None:
    class StubbornProcess(FakeProcess):
        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

    process = StubbornProcess()
    monkeypatch.setattr(start, "CHILD_STOP_TIMEOUT_SECONDS", 0)
    start._stop_process(process, "monitoring worker")
    assert process.terminated and process.killed
