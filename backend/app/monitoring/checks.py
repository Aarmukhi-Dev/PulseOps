import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class ServiceTarget:
    service_id: UUID
    name: str
    check_type: str
    target: str
    timeout_seconds: int
    check_interval_seconds: int
    expected_status_code: int | None


@dataclass(frozen=True)
class CheckResult:
    is_available: bool
    response_time_ms: int | None
    status_code: int | None = None
    error_type: str | None = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _is_expected_status(status_code: int, expected_status_code: int | None) -> bool:
    if expected_status_code is not None:
        return status_code == expected_status_code
    return 200 <= status_code < 300


def _network_error_type(error: BaseException) -> str:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    return "connection_error"


def check_http(target: ServiceTarget) -> CheckResult:
    try:
        parsed = urlsplit(target.target)
        parsed_port = parsed.port
    except ValueError:
        return CheckResult(False, None, error_type="invalid_target")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (parsed_port is not None and not 1 <= parsed_port <= 65535)
    ):
        return CheckResult(False, None, error_type="invalid_target")

    request = urllib.request.Request(
        target.target,
        headers={"User-Agent": "PulseOpsMonitor/1.0", "Accept": "*/*"},
        method="GET",
    )
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=target.timeout_seconds) as response:
            status_code = int(response.status)
        available = _is_expected_status(status_code, target.expected_status_code)
        return CheckResult(
            is_available=available,
            response_time_ms=_elapsed_ms(started_at),
            status_code=status_code,
            error_type=None if available else "http_status",
        )
    except urllib.error.HTTPError as error:
        status_code = int(error.code)
        error.close()
        available = _is_expected_status(status_code, target.expected_status_code)
        return CheckResult(
            is_available=available,
            response_time_ms=_elapsed_ms(started_at),
            status_code=status_code,
            error_type=None if available else "http_status",
        )
    except ValueError:
        return CheckResult(False, _elapsed_ms(started_at), error_type="invalid_target")
    except (TimeoutError, socket.timeout, ssl.SSLError, urllib.error.URLError, OSError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        return CheckResult(
            is_available=False,
            response_time_ms=_elapsed_ms(started_at),
            error_type=_network_error_type(reason if isinstance(reason, BaseException) else error),
        )


def check_tcp(target: ServiceTarget) -> CheckResult:
    raw_target = target.target.strip()
    try:
        parsed = urlsplit(raw_target if "://" in raw_target else f"//{raw_target}")
    except ValueError:
        return CheckResult(False, None, error_type="invalid_target")
    if parsed.scheme not in {"", "tcp"} or not parsed.hostname:
        return CheckResult(False, None, error_type="invalid_target")
    try:
        port = parsed.port
    except ValueError:
        return CheckResult(False, None, error_type="invalid_target")
    if (
        port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return CheckResult(False, None, error_type="invalid_target")

    started_at = time.perf_counter()
    try:
        with socket.create_connection((parsed.hostname, port), timeout=target.timeout_seconds):
            pass
        return CheckResult(True, _elapsed_ms(started_at))
    except (TimeoutError, socket.timeout, OSError) as error:
        return CheckResult(False, _elapsed_ms(started_at), error_type=_network_error_type(error))


def check_service(target: ServiceTarget) -> CheckResult:
    if target.check_type == "http":
        return check_http(target)
    if target.check_type == "tcp":
        return check_tcp(target)
    return CheckResult(False, None, error_type="unsupported_check_type")
