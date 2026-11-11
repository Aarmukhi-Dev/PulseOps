from datetime import UTC
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest

from app.api.metrics import get_current_metrics
from app.core.metrics import MetricsUnavailableError, collect_current_metrics
from app.main import app


@pytest.fixture
def mocked_psutil():
    with (
        patch("app.core.metrics.psutil.cpu_percent", return_value=23.5) as cpu_percent,
        patch("app.core.metrics.psutil.cpu_count", side_effect=[8, 4]) as cpu_count,
        patch(
            "app.core.metrics.psutil.virtual_memory",
            return_value=SimpleNamespace(total=16_000, used=6_000, available=10_000, percent=37.5),
        ) as virtual_memory,
        patch(
            "app.core.metrics.psutil.disk_usage",
            return_value=SimpleNamespace(total=1_000_000, used=250_000, free=750_000, percent=25.0),
        ) as disk_usage,
    ):
        yield cpu_percent, cpu_count, virtual_memory, disk_usage


def test_collector_returns_live_psutil_values_and_utc_timestamp(mocked_psutil) -> None:
    cpu_percent, cpu_count, virtual_memory, disk_usage = mocked_psutil

    result = collect_current_metrics()

    assert result.cpu.usage_percent == 23.5
    assert result.cpu.logical_cores == 8
    assert result.cpu.physical_cores == 4
    assert result.memory.total_bytes == 16_000
    assert result.memory.used_bytes == 6_000
    assert result.memory.available_bytes == 10_000
    assert result.memory.usage_percent == 37.5
    assert result.disk.total_bytes == 1_000_000
    assert result.disk.used_bytes == 250_000
    assert result.disk.free_bytes == 750_000
    assert result.disk.usage_percent == 25.0
    assert result.collected_at.tzinfo == UTC
    cpu_percent.assert_called_once_with(interval=0.1)
    assert cpu_count.call_count == 2
    virtual_memory.assert_called_once_with()
    disk_usage.assert_called_once_with(result.disk.mountpoint)


def test_endpoint_returns_the_collected_metrics(mocked_psutil) -> None:
    result = get_current_metrics()

    assert result.cpu.usage_percent == 23.5
    assert result.memory.usage_percent == 37.5
    assert result.disk.usage_percent == 25.0


def test_metrics_endpoint_is_registered() -> None:
    assert "get" in app.openapi()["paths"]["/api/v1/metrics/current"]


def test_collector_does_not_substitute_values_when_psutil_fails() -> None:
    with patch("app.core.metrics.psutil.virtual_memory", side_effect=psutil.AccessDenied):
        with pytest.raises(MetricsUnavailableError):
            collect_current_metrics()


def test_endpoint_returns_service_unavailable_when_metrics_fail() -> None:
    from fastapi import HTTPException

    with patch("app.api.metrics.collect_current_metrics", side_effect=MetricsUnavailableError):
        with pytest.raises(HTTPException) as error:
            get_current_metrics()

    assert error.value.status_code == 503
    assert error.value.detail == "System metrics are temporarily unavailable"
