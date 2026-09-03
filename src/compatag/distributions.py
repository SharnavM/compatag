from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DistributionKind(StrEnum):
    WHEEL = "wheel"
    SDIST = "sdist"
    UNKNOWN = "unknown"


class DistributionFile(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    filename: str
    url: str

    version: str | None
    kind: DistributionKind

    hashes: dict[str, str]
    requires_python: str | None = None

    yanked: bool = False
    yanked_reason: str | None = None

    size: int | None = None
    upload_time: datetime | None = None

    parse_error: str | None = None


class ProjectDistributions(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    name: str
    api_version: str

    versions: tuple[str, ...]
    files: tuple[DistributionFile, ...]

    status: str = "active"
    status_reason: str | None = None
