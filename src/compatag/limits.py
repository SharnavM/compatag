from __future__ import annotations

MAX_ANALYSIS_CONCURRENCY = 32

MAX_MANIFEST_BYTES = 128 * 1024
MAX_MANIFEST_REQUIREMENTS = 100

MAX_REQUIREMENT_TEXT_LENGTH = 2048
MAX_EXTRA_GROUPS = 32
MAX_EXTRA_NAME_LENGTH = 64

PYPI_MAX_RESPONSE_BYTES = 16 * 1024 * 1024

PYPI_CACHE_TTL_SECONDS = 300.0
PYPI_CACHE_MAX_ENTRIES = 256

PYPI_MAX_CONNECTIONS = 16
PYPI_MAX_KEEPALIVE_CONNECTIONS = 8


class ResourceLimitError(ValueError):
    """A Compatag workload exceeds a deliberate resource limit."""


def validate_analysis_concurrency(
    value: int,
) -> None:
    if not 1 <= value <= MAX_ANALYSIS_CONCURRENCY:
        raise ResourceLimitError(
            f"max_concurrency must be between 1 and {MAX_ANALYSIS_CONCURRENCY}"
        )


def manifest_size_bytes(
    text: str,
) -> int:
    return len(text.encode("utf-8"))


def validate_manifest_payload(
    text: str,
) -> None:
    size = manifest_size_bytes(text)

    if size > MAX_MANIFEST_BYTES:
        raise ResourceLimitError(
            f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte input limit (received {size} bytes)"
        )


def validate_manifest_requirement_count(
    count: int,
) -> None:
    if count > MAX_MANIFEST_REQUIREMENTS:
        raise ResourceLimitError(
            f"manifest declares {count} requirement "
            "entries; the tool limit is "
            f"{MAX_MANIFEST_REQUIREMENTS}"
        )
