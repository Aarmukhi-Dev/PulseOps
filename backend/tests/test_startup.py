import subprocess
import sys
from pathlib import Path

import start


def test_start_runs_migrations_from_backend_root_then_execs_uvicorn(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    exec_calls: list[tuple[str, list[str]]] = []
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(start.subprocess, "run", fake_run)
    monkeypatch.setattr(start.os, "execv", lambda executable, args: exec_calls.append((executable, args)))

    assert start.main() == 0

    assert calls == [
        ([sys.executable, "-m", "alembic", "upgrade", "head"], {"cwd": Path(start.__file__).resolve().parent, "check": True})
    ]
    assert exec_calls == [
        (
            sys.executable,
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        )
    ]


def test_start_uses_platform_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: None)
    exec_calls: list[list[str]] = []
    monkeypatch.setattr(start.os, "execv", lambda _executable, args: exec_calls.append(args))

    assert start.main() == 0
    assert exec_calls[0][-1] == "8123"


def test_start_refuses_to_run_uvicorn_if_migration_fails(monkeypatch, capsys) -> None:
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setattr(
        start.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, args[0])),
    )
    exec_calls: list[list[str]] = []
    monkeypatch.setattr(start.os, "execv", lambda _executable, args: exec_calls.append(args))

    assert start.main() == 1
    assert not exec_calls
    assert "migration failed" in capsys.readouterr().err.lower()


def test_start_rejects_invalid_port_before_running_migrations(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "not-a-port")
    migration_calls: list[bool] = []
    monkeypatch.setattr(start.subprocess, "run", lambda *args, **kwargs: migration_calls.append(True))

    assert start.main() == 2
    assert not migration_calls
