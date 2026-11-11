import argparse
import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Incident, IncidentEvent, MonitoredService, ServiceCheck
from app.monitoring.checks import CheckResult, ServiceTarget, check_service

logger = logging.getLogger("pulseops.monitoring")
POLL_INTERVAL_SECONDS = 1.0
ACTIVE_INCIDENT_STATUSES = ("open", "acknowledged")


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def _target_from_service(service: MonitoredService) -> ServiceTarget:
    return ServiceTarget(
        service_id=service.id,
        name=service.name,
        check_type=service.check_type,
        target=service.target,
        timeout_seconds=service.timeout_seconds,
        check_interval_seconds=service.check_interval_seconds,
        expected_status_code=service.expected_status_code,
    )


def record_check_result(
    target: ServiceTarget,
    result: CheckResult,
    session_factory: sessionmaker[Session] = SessionLocal,
) -> bool:
    """Persist one result and atomically apply any incident transition."""
    db = session_factory()
    try:
        service = db.scalar(
            select(MonitoredService)
            .where(MonitoredService.id == target.service_id)
            .with_for_update()
        )
        if service is None or not service.is_enabled:
            db.rollback()
            return False

        checked_at = datetime.now(UTC)
        previous_status = service.current_status
        check = ServiceCheck(
            service_id=service.id,
            checked_at=checked_at,
            is_available=result.is_available,
            response_time_ms=result.response_time_ms,
            status_code=result.status_code,
            error_type=result.error_type,
        )
        db.add(check)
        db.flush()

        service.current_status = "healthy" if result.is_available else "unhealthy"
        service.last_checked_at = checked_at
        service.last_response_time_ms = result.response_time_ms

        active_incident = db.scalar(
            select(Incident)
            .where(
                Incident.service_id == service.id,
                Incident.status.in_(ACTIVE_INCIDENT_STATUSES),
            )
            .with_for_update()
        )

        if result.is_available:
            if active_incident is not None:
                active_incident.status = "resolved"
                active_incident.resolved_at = checked_at
                db.add(
                    IncidentEvent(
                        incident_id=active_incident.id,
                        event_type="resolved",
                        payload={
                            "source": "monitor",
                            "check_id": str(check.id),
                            "response_time_ms": result.response_time_ms,
                            "status_code": result.status_code,
                        },
                    )
                )
        elif active_incident is None and previous_status != "unhealthy":
            incident = Incident(
                service_id=service.id,
                title="Monitored service unavailable",
                description="An automated availability check failed.",
                severity="high",
                status="open",
                started_at=checked_at,
            )
            db.add(incident)
            db.flush()
            db.add(
                IncidentEvent(
                    incident_id=incident.id,
                    event_type="created",
                    payload={
                        "source": "monitor",
                        "check_id": str(check.id),
                        "response_time_ms": result.response_time_ms,
                        "status_code": result.status_code,
                        "error_type": result.error_type,
                    },
                )
            )

        db.commit()
        _log(
            logging.WARNING if not result.is_available else logging.INFO,
            "service_check_completed",
            service_id=str(service.id),
            check_type=target.check_type,
            is_available=result.is_available,
            response_time_ms=result.response_time_ms,
            status_code=result.status_code,
            error_type=result.error_type,
        )
        return True
    except Exception as exc:
        db.rollback()
        _log(
            logging.ERROR,
            "service_check_persistence_failed",
            service_id=str(target.service_id),
            exception_type=type(exc).__name__,
        )
        return False
    finally:
        db.close()


def process_service_check(
    target: ServiceTarget,
    session_factory: sessionmaker[Session] = SessionLocal,
    check_function: Callable[[ServiceTarget], CheckResult] = check_service,
) -> bool:
    try:
        result = check_function(target)
    except Exception as exc:
        # Do not persist an invented result if the checker itself failed unexpectedly.
        _log(
            logging.ERROR,
            "service_check_execution_failed",
            service_id=str(target.service_id),
            exception_type=type(exc).__name__,
        )
        return False
    return record_check_result(target, result, session_factory)


def load_enabled_targets(session_factory: sessionmaker[Session] = SessionLocal) -> list[ServiceTarget]:
    with session_factory() as db:
        services = db.scalars(
            select(MonitoredService)
            .where(MonitoredService.is_enabled.is_(True))
            .order_by(MonitoredService.created_at, MonitoredService.id)
        ).all()
        return [_target_from_service(service) for service in services]


def run_worker(
    stop_event: threading.Event,
    max_concurrent_checks: int,
    session_factory: sessionmaker[Session] = SessionLocal,
    check_function: Callable[[ServiceTarget], CheckResult] = check_service,
) -> None:
    if max_concurrent_checks < 1:
        raise ValueError("max_concurrent_checks must be at least 1")

    scheduled_at: dict[UUID, float] = {}
    configured_intervals: dict[UUID, int] = {}
    active: dict[UUID, Future[bool]] = {}
    executor = ThreadPoolExecutor(max_workers=max_concurrent_checks, thread_name_prefix="pulseops-check")
    _log(logging.INFO, "monitoring_worker_started", max_concurrent_checks=max_concurrent_checks)

    try:
        while not stop_event.is_set():
            try:
                targets = load_enabled_targets(session_factory)
            except Exception as exc:
                _log(logging.ERROR, "monitoring_service_refresh_failed", exception_type=type(exc).__name__)
                stop_event.wait(POLL_INTERVAL_SECONDS)
                continue

            now = time.monotonic()
            enabled = {target.service_id: target for target in targets}

            for service_id, future in list(active.items()):
                if service_id not in enabled and future.cancel():
                    active.pop(service_id)
                    scheduled_at.pop(service_id, None)
                    configured_intervals.pop(service_id, None)
                elif future.done():
                    try:
                        future.result()
                    except Exception as exc:
                        _log(
                            logging.ERROR,
                            "monitoring_task_failed",
                            service_id=str(service_id),
                            exception_type=type(exc).__name__,
                        )
                    active.pop(service_id)
                    current = enabled.get(service_id)
                    if current is None:
                        scheduled_at.pop(service_id, None)
                        configured_intervals.pop(service_id, None)
                    else:
                        scheduled_at[service_id] = time.monotonic() + current.check_interval_seconds
                        configured_intervals[service_id] = current.check_interval_seconds

            for service_id in list(scheduled_at):
                if service_id not in enabled and service_id not in active:
                    scheduled_at.pop(service_id, None)
                    configured_intervals.pop(service_id, None)

            now = time.monotonic()
            for target in targets:
                service_id = target.service_id
                if service_id in active:
                    continue
                if service_id not in scheduled_at:
                    scheduled_at[service_id] = now
                    configured_intervals[service_id] = target.check_interval_seconds
                elif configured_intervals.get(service_id) != target.check_interval_seconds:
                    scheduled_at[service_id] = now
                    configured_intervals[service_id] = target.check_interval_seconds

                if len(active) >= max_concurrent_checks:
                    break
                if now >= scheduled_at[service_id]:
                    active[service_id] = executor.submit(
                        process_service_check,
                        target,
                        session_factory,
                        check_function,
                    )
                    # A service cannot be scheduled again until its current check completes.
                    scheduled_at[service_id] = float("inf")

            stop_event.wait(POLL_INTERVAL_SECONDS)
    finally:
        for future in active.values():
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        _log(logging.INFO, "monitoring_worker_stopped")


def main() -> None:
    if not settings.monitoring_worker_enabled:
        raise SystemExit("Monitoring worker is disabled by deployment policy")
    parser = argparse.ArgumentParser(description="Monitor enabled PulseOps services.")
    parser.add_argument(
        "--max-concurrent-checks",
        type=int,
        default=os.environ.get("PULSEOPS_MAX_CONCURRENT_CHECKS", "10"),
        help="maximum in-flight checks (default: PULSEOPS_MAX_CONCURRENT_CHECKS or 10)",
    )
    args = parser.parse_args()
    if args.max_concurrent_checks < 1:
        parser.error("--max-concurrent-checks must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop_event = threading.Event()

    def request_shutdown(signum: int, _frame: object) -> None:
        _log(logging.INFO, "monitoring_shutdown_requested", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    run_worker(stop_event, args.max_concurrent_checks)


if __name__ == "__main__":
    main()
