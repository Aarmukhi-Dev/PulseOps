from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CpuMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_percent: float = Field(ge=0, le=100)
    logical_cores: int = Field(gt=0)
    physical_cores: int | None = Field(default=None, gt=0)


class MemoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    usage_percent: float = Field(ge=0, le=100)


class DiskMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mountpoint: str
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    usage_percent: float = Field(ge=0, le=100)


class CurrentMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: datetime
    cpu: CpuMetrics
    memory: MemoryMetrics
    disk: DiskMetrics
