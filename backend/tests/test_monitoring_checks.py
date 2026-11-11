import socket
import urllib.error
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from app.monitoring.checks import CheckResult, ServiceTarget, check_http, check_service, check_tcp


def target(url: str, *, check_type: str = "http", expected_status_code: int | None = None) -> ServiceTarget:
    return ServiceTarget(
        service_id=uuid4(),
        name="Mock service",
        check_type=check_type,
        target=url,
        timeout_seconds=3,
        check_interval_seconds=30,
        expected_status_code=expected_status_code,
    )


@pytest.mark.parametrize("url", ["http://service.example.test/health", "https://service.example.test/health"])
def test_http_and_https_checks_use_timeout_and_mocked_response(url: str) -> None:
    response = Mock()
    response.status = 200
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    with patch("app.monitoring.checks.urllib.request.urlopen", return_value=response) as urlopen:
        result = check_http(target(url))

    assert result.is_available is True
    assert result.status_code == 200
    assert result.error_type is None
    request = urlopen.call_args.args[0]
    assert request.full_url == url
    assert "Authorization" not in request.headers
    assert urlopen.call_args.kwargs["timeout"] == 3


def test_expected_http_status_is_used() -> None:
    response = Mock()
    response.status = 204
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    with patch("app.monitoring.checks.urllib.request.urlopen", return_value=response):
        result = check_http(target("https://service.example.test", expected_status_code=204))
    assert result.is_available is True


def test_http_error_is_recorded_without_reading_or_storing_its_body() -> None:
    error = urllib.error.HTTPError("https://service.example.test", 503, "Unavailable", {}, None)
    with patch("app.monitoring.checks.urllib.request.urlopen", side_effect=error):
        result = check_http(target("https://service.example.test"))
    assert result == CheckResult(False, result.response_time_ms, status_code=503, error_type="http_status")


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [(socket.timeout(), "timeout"), (urllib.error.URLError("connection refused"), "connection_error")],
)
def test_http_network_errors_become_unavailable_results(exception: Exception, expected_error: str) -> None:
    with patch("app.monitoring.checks.urllib.request.urlopen", side_effect=exception):
        result = check_http(target("https://service.example.test"))
    assert result.is_available is False
    assert result.error_type == expected_error
    assert result.status_code is None
    assert result.response_time_ms is not None


def test_http_target_with_embedded_credentials_is_rejected_without_request() -> None:
    with patch("app.monitoring.checks.urllib.request.urlopen") as urlopen:
        result = check_http(target("https://user:secret@service.example.test/health"))
    assert result == CheckResult(False, None, error_type="invalid_target")
    urlopen.assert_not_called()


def test_tcp_check_uses_mocked_connection_and_service_timeout() -> None:
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    with patch("app.monitoring.checks.socket.create_connection", return_value=connection) as connect:
        result = check_service(target("service.example.test:443", check_type="tcp"))
    assert result.is_available is True
    assert result.error_type is None
    assert connect.call_args.args[0] == ("service.example.test", 443)
    assert connect.call_args.kwargs["timeout"] == 3


def test_tcp_timeout_is_reported_as_unavailable() -> None:
    with patch("app.monitoring.checks.socket.create_connection", side_effect=socket.timeout()):
        result = check_tcp(target("service.example.test:443", check_type="tcp"))
    assert result.is_available is False
    assert result.error_type == "timeout"


def test_unsupported_check_type_is_a_safe_failure() -> None:
    result = check_service(target("anything", check_type="icmp"))
    assert result == CheckResult(False, None, error_type="unsupported_check_type")
