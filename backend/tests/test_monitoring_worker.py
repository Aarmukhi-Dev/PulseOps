import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Incident, IncidentEvent, MonitoredService, ServiceCheck, User
from app.monitoring.checks import CheckResult, ServiceTarget
from app.monitoring import worker
from app.monitoring.worker import load_enabled_targets, record_check_result, run_worker


class FakeSession:
    def __init__(self, scalar_results):
        self.scalar_results = list(scalar_results)
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def scalar(self, _statement):
        return self.scalar_results.pop(0)

    def add(self, item):
        self.added.append(item)

    def flush(self):
        for item in self.added:
            if isinstance(item, (ServiceCheck, Incident, IncidentEvent)) and item.id is None:
                item.id = uuid4()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def make_target(service_id=None) -> ServiceTarget:
    return ServiceTarget(
        service_id=service_id or uuid4(),
        name="Payments",
        check_type="http",
        target="https://payments.example.test/health",
        timeout_seconds=5,
        check_interval_seconds=30,
        expected_status_code=200,
    )


def make_service(service_id, status="unknown", enabled=True):
    return SimpleNamespace(id=service_id, name="Payments", current_status=status, is_enabled=enabled)


def test_unhealthy_transition_creates_one_incident_and_auditable_event(caplog) -> None:
    service_id = uuid4()
    service = make_service(service_id)
    first = FakeSession([service, None])
    target = make_target(service_id)

    with caplog.at_level("WARNING", logger="pulseops.monitoring"):
        assert record_check_result(target, CheckResult(False, 125, status_code=503, error_type="http_status"), lambda: first)

    incidents = [item for item in first.added if isinstance(item, Incident)]
    events = [item for item in first.added if isinstance(item, IncidentEvent)]
    assert len(incidents) == len(events) == 1
    assert incidents[0].status == "open"
    assert events[0].event_type == "created"
    assert events[0].payload["source"] == "monitor"
    assert events[0].payload["response_time_ms"] == 125
    assert "target" not in events[0].payload
    assert "payments.example.test" not in caplog.text
    log_entry = json.loads(caplog.records[-1].message)
    assert log_entry["event"] == "service_check_completed"
    assert log_entry["error_type"] == "http_status"
    assert service.current_status == "unhealthy"
    assert first.committed and first.closed

    # A later failure with unhealthy state and an existing active incident adds only a check row.
    repeated = FakeSession([service, incidents[0]])
    assert record_check_result(target, CheckResult(False, 130, status_code=503, error_type="http_status"), lambda: repeated)
    assert sum(isinstance(item, Incident) for item in repeated.added) == 0
    assert sum(isinstance(item, IncidentEvent) for item in repeated.added) == 0
    assert sum(isinstance(item, ServiceCheck) for item in repeated.added) == 1


def test_recovery_resolves_active_incident_and_appends_event() -> None:
    service_id = uuid4()
    service = make_service(service_id, status="unhealthy")
    incident = SimpleNamespace(id=uuid4(), status="acknowledged", resolved_at=None)
    session = FakeSession([service, incident])

    assert record_check_result(make_target(service_id), CheckResult(True, 42, status_code=200), lambda: session)

    events = [item for item in session.added if isinstance(item, IncidentEvent)]
    assert service.current_status == "healthy"
    assert incident.status == "resolved"
    assert incident.resolved_at is not None
    assert len(events) == 1
    assert events[0].event_type == "resolved"
    assert events[0].payload["source"] == "monitor"


def test_disabled_service_result_is_not_recorded() -> None:
    service = make_service(uuid4(), enabled=False)
    session = FakeSession([service])

    assert record_check_result(make_target(service.id), CheckResult(True, 12, status_code=200), lambda: session) is False
    assert session.added == []
    assert session.rolled_back and session.closed


def test_load_enabled_targets_excludes_disabled_services() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
        connection.execute("PRAGMA foreign_keys=ON")

    User.__table__.create(engine)
    MonitoredService.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    user = User(email="monitor@example.test", display_name="Monitor", password_hash="$argon2id$test")
    with factory.begin() as db:
        db.add(user)
        db.flush()
        enabled = MonitoredService(name="enabled", target="https://enabled.example.test", created_by=user.id)
        disabled = MonitoredService(
            name="disabled", target="https://disabled.example.test", created_by=user.id, is_enabled=False
        )
        db.add_all([enabled, disabled])
        db.flush()
        enabled_id = enabled.id

    assert [target.service_id for target in load_enabled_targets(factory)] == [enabled_id]
    engine.dispose()


def test_worker_validates_concurrency_limit() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run_worker(threading.Event(), 0)


class FakeLockResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value


class FakeLockConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.backend_pid = 1234
        self.statements = []
        self.closed = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if "pg_backend_pid" in str(statement):
            return FakeLockResult(self.backend_pid)
        return FakeLockResult(self.acquired if "try_advisory" in str(statement) else True)

    def close(self) -> None:
        self.closed = True


class FakeLockEngine:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def test_worker_advisory_lock_acquisition_holds_direct_session(monkeypatch) -> None:
    connection = FakeLockConnection(acquired=True)
    engine = FakeLockEngine(connection)
    factory_calls = []

    def engine_factory(url, **kwargs):
        factory_calls.append((url, kwargs))
        return engine

    monkeypatch.setattr(worker, "create_engine", engine_factory)
    lock = worker.try_acquire_worker_lock("postgresql+psycopg://direct.example/db")

    assert lock is not None
    assert factory_calls[0][0].startswith("postgresql+psycopg://direct.example")
    assert factory_calls[0][1]["poolclass"] is worker.NullPool
    assert "pg_try_advisory_lock" in connection.statements[0][0]
    assert not connection.closed and not engine.disposed
    lock.assert_held()
    assert "pg_backend_pid" in connection.statements[1][0]
    lock.close()
    assert "pg_advisory_unlock" in connection.statements[3][0]
    assert connection.closed and engine.disposed


def test_worker_lock_contention_closes_connection_without_owning_lock(monkeypatch) -> None:
    connection = FakeLockConnection(acquired=False)
    engine = FakeLockEngine(connection)
    monkeypatch.setattr(worker, "create_engine", lambda *_args, **_kwargs: engine)

    assert worker.try_acquire_worker_lock("postgresql+psycopg://direct.example/db") is None
    assert connection.closed and engine.disposed
    assert len(connection.statements) == 1


def test_worker_waits_on_lock_contention_and_does_not_enter_check_loop(monkeypatch) -> None:
    attempts = []

    class StopAfterWait:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True

    stop_event = StopAfterWait()
    assert worker.wait_for_worker_lock(
        stop_event,
        "direct-url",
        retry_seconds=0,
        lock_attempt=lambda _url: attempts.append(True) or None,
    ) is None
    assert len(attempts) == 1


def test_worker_retries_lock_until_previous_deployment_releases_it() -> None:
    connection = FakeLockConnection(acquired=True)
    lock = worker.WorkerAdvisoryLock(FakeLockEngine(connection), connection, backend_pid=1234)
    attempts = iter([None, lock])
    calls = []

    class StopAfterAcquisition:
        def is_set(self):
            return False

        def wait(self, _seconds):
            calls.append("waited")

    acquired = worker.wait_for_worker_lock(
        StopAfterAcquisition(),
        "direct-url",
        retry_seconds=0,
        lock_attempt=lambda _url: next(attempts),
    )
    assert acquired is lock
    assert calls == ["waited"]
    lock.close()


def test_worker_lock_connection_failure_is_propagated_for_supervised_restart(monkeypatch) -> None:
    engine = FakeLockEngine(None)

    def fail_to_connect():
        raise RuntimeError("database unavailable")

    engine.connect = fail_to_connect
    monkeypatch.setattr(worker, "create_engine", lambda *_args, **_kwargs: engine)
    with pytest.raises(RuntimeError, match="database unavailable"):
        worker.try_acquire_worker_lock("direct-url")
    assert engine.disposed


def test_worker_stops_scheduling_when_lock_session_changes(monkeypatch) -> None:
    connection = FakeLockConnection(acquired=True)
    lock = worker.WorkerAdvisoryLock(FakeLockEngine(connection), connection, backend_pid=1234)
    connection.backend_pid = 5678
    target_loads = []
    monkeypatch.setattr(worker, "load_enabled_targets", lambda *_args: target_loads.append(True))

    stop_event = threading.Event()
    with pytest.raises(worker.WorkerLockLost, match="session changed"):
        run_worker(stop_event, 1, lock_guard=lock)

    assert stop_event.is_set()
    assert target_loads == []


def test_worker_main_does_not_check_services_while_lock_is_contended(monkeypatch) -> None:
    monkeypatch.setattr(worker.settings, "monitoring_worker_enabled", True)
    monkeypatch.setattr(worker.settings, "worker_lock_database_url", "postgresql+psycopg://direct/db")
    monkeypatch.setattr(worker.argparse.ArgumentParser, "parse_args", lambda _self: SimpleNamespace(max_concurrent_checks=1))
    monkeypatch.setattr(worker.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(worker, "wait_for_worker_lock", lambda *_args: None)
    checks = []
    monkeypatch.setattr(worker, "run_worker", lambda *_args: checks.append(True))

    worker.main()
    assert not checks


def test_production_policy_prevents_worker_start(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "monitoring_worker_enabled", False)
    with pytest.raises(SystemExit, match="disabled by deployment policy"):
        worker.main()


def test_worker_requires_lock_url_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(worker.settings, "monitoring_worker_enabled", True)
    monkeypatch.setattr(worker.settings, "worker_lock_database_url", None)
    with pytest.raises(SystemExit, match="WORKER_LOCK_DATABASE_URL is required"):
        worker.main()


def test_worker_respects_concurrency_cap_and_waits_for_active_checks(monkeypatch) -> None:
    targets = [make_target() for _ in range(4)]
    monkeypatch.setattr(worker, "load_enabled_targets", lambda _factory: targets)
    monkeypatch.setattr(worker, "process_service_check", lambda target, _factory, check_fn: check_fn(target))

    active = 0
    max_active = 0
    lock = threading.Lock()
    two_checks_started = threading.Event()
    release_checks = threading.Event()
    stop_event = threading.Event()
    errors = []

    def blocking_check(_target):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                two_checks_started.set()
        release_checks.wait(timeout=3)
        with lock:
            active -= 1
        return CheckResult(True, 10, status_code=200)

    def run() -> None:
        try:
            run_worker(stop_event, 2, check_function=blocking_check)
        except Exception as exc:  # surface worker-thread exceptions in the test thread
            errors.append(exc)

    worker_thread = threading.Thread(target=run)
    worker_thread.start()
    assert two_checks_started.wait(timeout=3)
    stop_event.set()
    release_checks.set()
    worker_thread.join(timeout=3)

    assert not worker_thread.is_alive()
    assert errors == []
    assert max_active == 2
