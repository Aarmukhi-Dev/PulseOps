from datetime import UTC, datetime
from pathlib import Path

import psutil

from app.schemas.metrics import CpuMetrics, CurrentMetricsResponse, DiskMetrics, MemoryMetrics

CPU_SAMPLE_INTERVAL_SECONDS = 0.1


class MetricsUnavailableError(Exception):
    """Raised when the host metrics provider cannot collect a real reading."""


def collect_current_metrics() -> CurrentMetricsResponse:
    """Collect one live snapshot from the machine running the API process."""
    mountpoint = Path.home().anchor or "/"
    try:
        cpu_percent = psutil.cpu_percent(interval=CPU_SAMPLE_INTERVAL_SECONDS)
        logical_cores = psutil.cpu_count(logical=True)
        if logical_cores is None:
            raise MetricsUnavailableError("Logical CPU count is unavailable")

        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(mountpoint)

        return CurrentMetricsResponse(
            collected_at=datetime.now(UTC),
            cpu=CpuMetrics(
                usage_percent=cpu_percent,
                logical_cores=logical_cores,
                physical_cores=psutil.cpu_count(logical=False),
            ),
            memory=MemoryMetrics(
                total_bytes=memory.total,
                used_bytes=memory.used,
                available_bytes=memory.available,
                usage_percent=memory.percent,
            ),
            disk=DiskMetrics(
                mountpoint=mountpoint,
                total_bytes=disk.total,
                used_bytes=disk.used,
                free_bytes=disk.free,
                usage_percent=disk.percent,
            ),
        )
    except (psutil.Error, OSError) as exc:
        raise MetricsUnavailableError("The operating system could not provide a metrics reading") from exc
