import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit
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
    return status_code == expected_status_code if expected_status_code is not None else 200 <= status_code < 300


def _network_error_type(error: BaseException) -> str:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    return "connection_error"


_BLOCKED_HOSTS = {"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan")
_SENSITIVE_QUERY_KEYS = {"access_token", "apikey", "api_key", "auth", "authorization", "credential", "credentials", "key", "password", "secret", "signature", "token"}


def _validated_addresses(host: str, port: int) -> list[tuple[int, str]]:
    normalized_host = host.rstrip(".").lower()
    if not normalized_host or normalized_host in _BLOCKED_HOSTS or normalized_host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError("non-public monitor target")
    try:
        literal = ipaddress.ip_address(normalized_host)
        candidates = [(socket.AF_INET6 if literal.version == 6 else socket.AF_INET, str(literal))]
    except ValueError:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        candidates = []
        for family, _socktype, _proto, _canonname, sockaddr in infos:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            candidates.append((family, sockaddr[0]))
    if not candidates:
        raise OSError("target did not resolve")
    result: list[tuple[int, str]] = []
    for family, address in candidates:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ValueError("non-public monitor target")
        result.append((family, address))
    return list(dict.fromkeys(result))


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, family: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._address = address
        self._family = family

    def connect(self) -> None:
        sock = socket.socket(self._family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sockaddr = (self._address, self.port, 0, 0) if self._family == socket.AF_INET6 else (self._address, self.port)
            sock.connect(sockaddr)
        except Exception:
            sock.close()
            raise
        self.sock = sock


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    def connect(self) -> None:
        raw = socket.socket(self._family, socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            sockaddr = (self._address, self.port, 0, 0) if self._family == socket.AF_INET6 else (self._address, self.port)
            raw.connect(sockaddr)
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _parse_http_url(value: str):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(key.lower().replace("-", "_") in _SENSITIVE_QUERY_KEYS for key, _value in parse_qsl(parsed.query, keep_blank_values=True))
        or (port is not None and not 1 <= port <= 65535)
        or len(value) > 2048
    ):
        raise ValueError("invalid URL")
    return parsed, port or (443 if parsed.scheme.lower() == "https" else 80)


def check_http(target: ServiceTarget) -> CheckResult:
    started = time.perf_counter()
    current_url = target.target
    try:
        for redirect_count in range(6):
            parsed, port = _parse_http_url(current_url)
            host = parsed.hostname
            addresses = _validated_addresses(host, port)
            connection_class = _PinnedHTTPSConnection if parsed.scheme.lower() == "https" else _PinnedHTTPConnection
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            response = None
            last_error: OSError | None = None
            for family, address in addresses:
                connection = connection_class(host, port, address, family, target.timeout_seconds)
                try:
                    connection.request("GET", path, headers={"User-Agent": "PulseOpsMonitor/1.0", "Accept": "*/*"})
                    response = connection.getresponse()
                    break
                except (TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
                    last_error = exc
                    connection.close()
            if response is None:
                raise last_error or OSError("connection failed")
            status_code = int(response.status)
            location = response.getheader("Location")
            response.close()
            connection.close()
            if status_code in {301, 302, 303, 307, 308} and location:
                if redirect_count == 5:
                    raise ValueError("too many redirects")
                current_url = urljoin(current_url, location)
                continue
            available = _is_expected_status(status_code, target.expected_status_code)
            return CheckResult(available, _elapsed_ms(started), status_code, None if available else "http_status")
        raise ValueError("too many redirects")
    except ValueError:
        return CheckResult(False, _elapsed_ms(started), error_type="invalid_target")
    except (TimeoutError, socket.timeout, ssl.SSLError, OSError) as error:
        return CheckResult(False, _elapsed_ms(started), error_type=_network_error_type(error))


def _parse_tcp_target(value: str) -> tuple[str, int]:
    normalized = value.strip()
    parsed = urlsplit(normalized if "://" in normalized else f"//{normalized}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    if (
        parsed.scheme not in {"", "tcp"}
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or len(normalized) > 2048
    ):
        raise ValueError("invalid target")
    return parsed.hostname, port


def check_tcp(target: ServiceTarget) -> CheckResult:
    started = time.perf_counter()
    try:
        host, port = _parse_tcp_target(target.target)
        addresses = _validated_addresses(host, port)
    except ValueError:
        return CheckResult(False, None, error_type="invalid_target")
    except OSError as error:
        return CheckResult(False, _elapsed_ms(started), error_type=_network_error_type(error))
    last_error: OSError | None = None
    for family, address in addresses:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(target.timeout_seconds)
        try:
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            sock.connect(sockaddr)
            return CheckResult(True, _elapsed_ms(started))
        except (TimeoutError, socket.timeout, OSError) as error:
            last_error = error
        finally:
            sock.close()
    return CheckResult(False, _elapsed_ms(started), error_type=_network_error_type(last_error or OSError()))


def check_service(target: ServiceTarget) -> CheckResult:
    if target.check_type == "http":
        return check_http(target)
    if target.check_type == "tcp":
        return check_tcp(target)
    return CheckResult(False, None, error_type="unsupported_check_type")
