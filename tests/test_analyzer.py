import pytest

from compatag.analyzer import (
    CheckSeverity,
    PackageCheckStatus,
    check_package,
)
from compatag.distributions import (
    DistributionFile,
    DistributionKind,
    ProjectDistributions,
)
from compatag.pypi import (
    ProjectNotFoundError,
    PyPIRequestError,
    PyPIResponseError,
)
from compatag.targets import TargetEnvironment


def _wheel(
    filename: str,
    version: str,
    *,
    requires_python: str | None = None,
    yanked: bool = False,
    yanked_reason: str | None = None,
) -> DistributionFile:
    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.WHEEL,
        hashes={"sha256": "digest"},
        requires_python=requires_python,
        yanked=yanked,
        yanked_reason=yanked_reason,
    )


def _sdist(
    filename: str,
    version: str,
    *,
    requires_python: str | None = None,
    yanked: bool = False,
    yanked_reason: str | None = None,
) -> DistributionFile:
    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.SDIST,
        hashes={"sha256": "digest"},
        requires_python=requires_python,
        yanked=yanked,
        yanked_reason=yanked_reason,
    )


def _project(
    *,
    versions: tuple[str, ...],
    files: tuple[DistributionFile, ...],
    status: str = "active",
    status_reason: str | None = None,
) -> ProjectDistributions:
    return ProjectDistributions(
        name="demo",
        api_version="1.4",
        versions=versions,
        files=files,
        status=status,
        status_reason=status_reason,
    )


class StubPyPIClient:
    def __init__(
        self,
        project: ProjectDistributions | None = None,
        error: Exception | None = None,
    ) -> None:
        self.project = project
        self.error = error
        self.requests: list[str] = []

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        self.requests.append(name)

        if self.error is not None:
            raise self.error

        if self.project is None:
            raise AssertionError("StubPyPIClient has no project configured")

        return self.project


_WIN_311 = TargetEnvironment(
    python_version="3.11",
    platform="win_amd64",
)

_LINUX_ARM_311 = TargetEnvironment(
    python_version="3.11",
    platform="manylinux_2_17_aarch64",
)


@pytest.mark.asyncio
async def test_compatible_platform_wheel_passes() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-cp311-cp311-win_amd64.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.PASS
    assert result.status is PackageCheckStatus.WHEEL_AVAILABLE
    assert result.selected_version == "1.0"

    assert result.artifact is not None
    assert result.artifact.filename == ("demo-1.0-cp311-cp311-win_amd64.whl")


@pytest.mark.asyncio
async def test_universal_wheel_has_distinct_status() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _LINUX_ARM_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.PASS
    assert result.status is PackageCheckStatus.UNIVERSAL_WHEEL_AVAILABLE


@pytest.mark.asyncio
async def test_best_matching_wheel_is_selected() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
            _wheel(
                "demo-1.0-cp311-cp311-win_amd64.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.artifact is not None
    assert result.artifact.filename == ("demo-1.0-cp311-cp311-win_amd64.whl")


@pytest.mark.asyncio
async def test_source_distribution_produces_warning() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _sdist(
                "demo-1.0.tar.gz",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.WARN
    assert result.status is PackageCheckStatus.SOURCE_BUILD_REQUIRED

    assert result.artifact is not None
    assert result.artifact.kind is DistributionKind.SDIST


@pytest.mark.asyncio
async def test_wrong_platform_wheel_is_not_compatible() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-cp311-cp311-win_amd64.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _LINUX_ARM_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.FAIL
    assert result.status is PackageCheckStatus.NO_COMPATIBLE_DISTRIBUTION


@pytest.mark.asyncio
async def test_newest_python_incompatible_release_is_skipped() -> None:
    project = _project(
        versions=("1.0", "2.0"),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
                requires_python=">=3.10",
            ),
            _wheel(
                "demo-2.0-py3-none-any.whl",
                "2.0",
                requires_python=">=3.12",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.status is PackageCheckStatus.UNIVERSAL_WHEEL_AVAILABLE
    assert result.selected_version == "1.0"


@pytest.mark.asyncio
async def test_newer_sdist_is_not_skipped_for_older_wheel() -> None:
    project = _project(
        versions=("1.0", "2.0"),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
            _sdist(
                "demo-2.0.tar.gz",
                "2.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.status is PackageCheckStatus.SOURCE_BUILD_REQUIRED

    assert result.selected_version == "2.0"


@pytest.mark.asyncio
async def test_requires_python_partial_minor_is_indeterminate() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
                requires_python=">=3.11.5",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.status is PackageCheckStatus.INDETERMINATE_REQUIRES_PYTHON

    assert "micro version" in result.summary


@pytest.mark.asyncio
async def test_invalid_requires_python_is_metadata_error() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
                requires_python="not-a-specifier",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN
    assert result.status is PackageCheckStatus.METADATA_ERROR


@pytest.mark.asyncio
async def test_marker_can_exclude_requirement_without_network_lookup() -> None:
    client = StubPyPIClient()

    result = await check_package(
        'demo>=1; sys_platform == "win32"',
        _LINUX_ARM_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.PASS
    assert result.status is PackageCheckStatus.NOT_APPLICABLE

    assert client.requests == []


@pytest.mark.asyncio
async def test_marker_is_evaluated_against_target_not_host() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        'demo; sys_platform == "linux"',
        _LINUX_ARM_311,
        client,  # type: ignore[arg-type]
    )

    assert result.status is PackageCheckStatus.UNIVERSAL_WHEEL_AVAILABLE

    assert client.requests == ["demo"]


@pytest.mark.asyncio
async def test_micro_version_marker_is_indeterminate() -> None:
    client = StubPyPIClient()

    result = await check_package(
        'demo; python_full_version >= "3.11.5"',
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.status is PackageCheckStatus.INDETERMINATE_MARKER

    assert client.requests == []


@pytest.mark.asyncio
async def test_version_constraint_can_produce_no_matching_release() -> None:
    project = _project(
        versions=("1.0", "2.0"),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
            _wheel(
                "demo-2.0-py3-none-any.whl",
                "2.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=3",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.FAIL
    assert result.status is PackageCheckStatus.NO_MATCHING_RELEASE


@pytest.mark.asyncio
async def test_final_release_is_preferred_over_newer_prerelease() -> None:
    project = _project(
        versions=("1.9", "2.0rc1"),
        files=(
            _wheel(
                "demo-1.9-py3-none-any.whl",
                "1.9",
            ),
            _wheel(
                "demo-2.0rc1-py3-none-any.whl",
                "2.0rc1",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.selected_version == "1.9"


@pytest.mark.asyncio
async def test_prerelease_is_used_when_no_final_release_matches() -> None:
    project = _project(
        versions=("2.0rc1",),
        files=(
            _wheel(
                "demo-2.0rc1-py3-none-any.whl",
                "2.0rc1",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.selected_version == "2.0rc1"

    assert result.status is PackageCheckStatus.UNIVERSAL_WHEEL_AVAILABLE


@pytest.mark.asyncio
async def test_yanked_release_is_skipped_when_older_release_is_usable() -> None:
    project = _project(
        versions=("1.0", "2.0"),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
            _wheel(
                "demo-2.0-py3-none-any.whl",
                "2.0",
                yanked=True,
                yanked_reason="Broken release",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.selected_version == "1.0"


@pytest.mark.asyncio
async def test_only_usable_yanked_artifact_is_failure() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
                yanked=True,
                yanked_reason="Regression",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo==1.0",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.FAIL
    assert result.status is PackageCheckStatus.YANKED_ONLY

    assert "Yanked reason: Regression" in result.notes


@pytest.mark.asyncio
async def test_direct_url_requirement_is_not_fetched() -> None:
    client = StubPyPIClient()

    result = await check_package(
        "demo @ https://example.test/demo.whl",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.status is PackageCheckStatus.UNSUPPORTED_REQUIREMENT

    assert client.requests == []


@pytest.mark.asyncio
async def test_invalid_requirement_is_reported() -> None:
    client = StubPyPIClient()

    result = await check_package(
        "not a valid requirement !!!",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.status is PackageCheckStatus.UNSUPPORTED_REQUIREMENT

    assert client.requests == []


@pytest.mark.asyncio
async def test_requested_extras_are_disclosed() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
        ),
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo[http]>=1",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.PASS
    assert any("extras" in note.lower() for note in result.notes)


@pytest.mark.asyncio
async def test_missing_project_is_failure() -> None:
    client = StubPyPIClient(error=ProjectNotFoundError("missing"))

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.FAIL

    assert result.status is PackageCheckStatus.PROJECT_NOT_FOUND


@pytest.mark.asyncio
async def test_network_failure_is_unknown() -> None:
    client = StubPyPIClient(error=PyPIRequestError("PyPI unavailable"))

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN
    assert result.status is PackageCheckStatus.NETWORK_ERROR


@pytest.mark.asyncio
async def test_bad_pypi_response_is_unknown() -> None:
    client = StubPyPIClient(error=PyPIResponseError("bad metadata"))

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN
    assert result.status is PackageCheckStatus.METADATA_ERROR


@pytest.mark.asyncio
async def test_non_active_project_status_is_preserved_as_note() -> None:
    project = _project(
        versions=("1.0",),
        files=(
            _wheel(
                "demo-1.0-py3-none-any.whl",
                "1.0",
            ),
        ),
        status="deprecated",
        status_reason="Use another project.",
    )

    client = StubPyPIClient(project)

    result = await check_package(
        "demo",
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert any("deprecated" in note for note in result.notes)
