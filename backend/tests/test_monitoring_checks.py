import socket
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from app.monitoring.checks import (
    CheckResult,
    ServiceTarget,
    _validated_addresses,
    check_http,
    check_service,
    check_tcp,
)


def target(url: str, *, check_type: str = "http", expected_status_code: int | None = None) -> ServiceTarget:
    return ServiceTarget(uuid4(), "Mock service", check_type, url, 3, 30, expected_status_code)


def dns_public(_host, _port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]


def response(status=200, location=None):
    result = Mock()
    result.status = status
    result.getheader.return_value = location
    result.close = Mock()
    return result


@pytest.mark.parametrize("url", ["http://service.example.test/health", "https://service.example.test/health"])
def test_http_and_https_use_validated_pinned_addresses(url: str) -> None:
    conn = Mock()
    conn.getresponse.return_value = response()
    with (
        patch("app.monitoring.checks.socket.getaddrinfo", side_effect=dns_public),
        patch("app.monitoring.checks._PinnedHTTPConnection", return_value=conn) as http_conn,
        patch("app.monitoring.checks._PinnedHTTPSConnection", return_value=conn) as https_conn,
    ):
        result = check_http(target(url))
    assert result == CheckResult(True, result.response_time_ms, 200, None)
    (https_conn if url.startswith("https") else http_conn).assert_called_once_with(
        "service.example.test", 443 if url.startswith("https") else 80, "93.184.216.34", socket.AF_INET, 3
    )
    assert conn.request.call_args.args[:2] == ("GET", "/health")
    assert "Authorization" not in conn.request.call_args.kwargs["headers"]


def test_expected_http_status_is_used() -> None:
    conn = Mock()
    conn.getresponse.return_value = response(204)
    with patch("app.monitoring.checks._validated_addresses", return_value=[(socket.AF_INET, "93.184.216.34")]), patch(
        "app.monitoring.checks._PinnedHTTPSConnection", return_value=conn
    ):
        result = check_http(target("https://service.example.test", expected_status_code=204))
    assert result.is_available and result.status_code == 204


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "https://user:secret@example.test/", "https://service.example.test/?api_key=private", "ftp://example.test/"])
def test_invalid_or_local_http_targets_are_rejected_before_connect(url: str) -> None:
    with patch("app.monitoring.checks._PinnedHTTPConnection") as connect, patch("app.monitoring.checks._PinnedHTTPSConnection") as connect_tls:
        result = check_http(target(url))
    assert not result.is_available and result.error_type == "invalid_target"
    connect.assert_not_called()
    connect_tls.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.2", "169.254.169.254", "192.168.1.2", "::1", "fe80::1"])
def test_private_loopback_and_link_local_dns_results_are_rejected(address: str) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    record = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
    with patch("app.monitoring.checks.socket.getaddrinfo", return_value=[record]):
        with pytest.raises(ValueError):
            _validated_addresses("service.example.test", 443)


def test_mixed_public_and_private_dns_answers_are_rejected() -> None:
    public = dns_public("", 443)[0]
    private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", 443))
    with patch("app.monitoring.checks.socket.getaddrinfo", return_value=[public, private]):
        with pytest.raises(ValueError):
            _validated_addresses("service.example.test", 443)


def test_http_redirect_revalidates_destination_and_blocks_private_hop() -> None:
    conn = Mock()
    conn.getresponse.return_value = response(302, "http://169.254.169.254/latest/meta-data/")
    with (
        patch("app.monitoring.checks._validated_addresses", side_effect=[[(socket.AF_INET, "93.184.216.34")], ValueError("private")]),
        patch("app.monitoring.checks._PinnedHTTPConnection", return_value=conn),
    ):
        result = check_http(target("http://service.example.test/"))
    assert not result.is_available and result.error_type == "invalid_target"
    conn.request.assert_called_once()


def test_tcp_check_connects_to_pinned_public_ip() -> None:
    sock = Mock()
    with patch("app.monitoring.checks._validated_addresses", return_value=[(socket.AF_INET, "93.184.216.34")]), patch(
        "app.monitoring.checks.socket.socket", return_value=sock
    ) as make_socket:
        result = check_tcp(target("service.example.test:443", check_type="tcp"))
    assert result.is_available
    make_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect.assert_called_once_with(("93.184.216.34", 443))


def test_tcp_private_target_is_rejected_without_opening_socket() -> None:
    with patch("app.monitoring.checks.socket.socket") as make_socket:
        result = check_tcp(target("127.0.0.1:5432", check_type="tcp"))
    assert not result.is_available and result.error_type == "invalid_target"
    make_socket.assert_not_called()


def test_unsupported_check_type_is_a_safe_failure() -> None:
    assert check_service(target("anything", check_type="icmp")) == CheckResult(False, None, error_type="unsupported_check_type")
