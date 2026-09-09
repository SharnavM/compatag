import asyncio

import pytest

from compatag.analyzer import CheckSeverity
from compatag.audit import (
    AuditVerbosity,
    ProjectPythonStatus,
    audit_manifest,
)
from compatag.distributions import (
    DistributionFile,
    DistributionKind,
    ProjectDistributions,
)
from compatag.manifests import (
    parse_pyproject,
    parse_requirements,
)
from compatag.pypi import PyPIRequestError
from compatag.targets import TargetEnvironment


def _wheel(
    name: str,
    *,
    version: str = "1.0",
    platform_tag: str = "py3-none-any",
) -> DistributionFile:
    filename = f"{name}-{version}-{platform_tag}.whl"

    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.WHEEL,
        hashes={"sha256": "digest"},
    )


def _sdist(
    name: str,
    *,
    version: str = "1.0",
) -> DistributionFile:
    filename = f"{name}-{version}.tar.gz"

    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.SDIST,
        hashes={"sha256": "digest"},
    )


def _project(
    name: str,
    files: tuple[
        DistributionFile,
        ...,
    ],
) -> ProjectDistributions:
    versions = tuple(sorted({file.version for file in files if file.version is not None}))

    return ProjectDistributions(
        name=name,
        api_version="1.4",
        versions=versions,
        files=files,
    )


class StubPyPIClient:
    def __init__(
        self,
        projects: dict[
            str,
            ProjectDistributions,
        ],
        *,
        delays: dict[str, float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.projects = projects
        self.delays = delays or {}
        self.error = error

        self.requests: list[str] = []

        self.active = 0
        self.max_active = 0

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        self.requests.append(name)

        self.active += 1
        self.max_active = max(
            self.max_active,
            self.active,
        )

        try:
            delay = self.delays.get(
                name,
                0.0,
            )

            if delay:
                await asyncio.sleep(delay)

            if self.error is not None:
                raise self.error

            return self.projects[name]
        finally:
            self.active -= 1


_WIN_311 = TargetEnvironment(
    python_version="3.11",
    platform="win_amd64",
)


@pytest.mark.asyncio
async def test_clean_manifest_passes() -> None:
    manifest = parse_requirements("alpha>=1\nbeta>=1\n")

    client = StubPyPIClient(
        {
            "alpha": _project(
                "alpha",
                (_wheel("alpha"),),
            ),
            "beta": _project(
                "beta",
                (_wheel("beta"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        verbosity=AuditVerbosity.ALL,
    )

    assert result.severity is CheckSeverity.PASS
    assert result.manifest_complete

    assert result.requirements_found == 2
    assert result.unique_checks == 2

    assert result.counts.passed == 2
    assert result.counts.warnings == 0
    assert result.counts.failures == 0
    assert result.counts.unknown == 0

    assert len(result.findings) == 2


@pytest.mark.asyncio
async def test_duplicate_requirement_is_checked_once_but_keeps_occurrences() -> None:
    manifest = parse_requirements("demo>=1\ndemo >=1\n")

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        verbosity=AuditVerbosity.ALL,
    )

    assert client.requests == ["demo"]

    assert result.requirements_found == 2
    assert result.unique_checks == 1

    assert result.counts.passed == 2

    assert len(result.findings) == 2

    assert result.findings[0].requirement.line_start == 1

    assert result.findings[1].requirement.line_start == 2


@pytest.mark.asyncio
async def test_package_checks_use_bounded_concurrency() -> None:
    names = (
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
    )

    manifest = parse_requirements("".join(f"{name}\n" for name in names))

    projects = {
        name: _project(
            name,
            (_wheel(name),),
        )
        for name in names
    }

    client = StubPyPIClient(
        projects,
        delays={name: 0.02 for name in names},
    )

    await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        max_concurrency=2,
    )

    assert client.max_active == 2


@pytest.mark.asyncio
async def test_finding_order_matches_manifest_not_completion_order() -> None:
    manifest = parse_requirements("alpha\nbeta\ngamma\n")

    client = StubPyPIClient(
        {
            "alpha": _project(
                "alpha",
                (_wheel("alpha"),),
            ),
            "beta": _project(
                "beta",
                (_wheel("beta"),),
            ),
            "gamma": _project(
                "gamma",
                (_wheel("gamma"),),
            ),
        },
        delays={
            "alpha": 0.03,
            "beta": 0.02,
            "gamma": 0.01,
        },
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        verbosity=AuditVerbosity.ALL,
    )

    assert [finding.requirement.name for finding in result.findings] == [
        "alpha",
        "beta",
        "gamma",
    ]


@pytest.mark.asyncio
async def test_source_build_warning_makes_audit_warn() -> None:
    manifest = parse_requirements("demo\n")

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_sdist("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.WARN
    assert result.counts.warnings == 1

    assert len(result.findings) == 1


@pytest.mark.asyncio
async def test_network_uncertainty_makes_audit_unknown() -> None:
    manifest = parse_requirements("demo\n")

    client = StubPyPIClient(
        {},
        error=PyPIRequestError("PyPI unavailable"),
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.counts.unknown == 1


@pytest.mark.asyncio
async def test_incomplete_manifest_is_unknown_when_known_requirements_pass() -> None:
    manifest = parse_requirements("demo\n-r private.txt\n")

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert not result.manifest_complete

    assert result.severity is CheckSeverity.UNKNOWN

    assert result.counts.manifest_errors == 1


@pytest.mark.asyncio
async def test_confirmed_failure_beats_incomplete_manifest() -> None:
    manifest = parse_requirements("demo\n-r private.txt\n")

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        platform_tag=("cp311-cp311-manylinux_2_17_x86_64"),
                    ),
                ),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.counts.failures == 1

    assert result.severity is CheckSeverity.FAIL


@pytest.mark.asyncio
async def test_project_requires_python_can_fail_audit() -> None:
    manifest = parse_pyproject(
        """
[project]
name = "demo-app"
requires-python = ">=3.12"
dependencies = ["demo"]
"""
    )

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.project_python.status is ProjectPythonStatus.INCOMPATIBLE

    assert result.project_python.severity is CheckSeverity.FAIL

    assert result.severity is CheckSeverity.FAIL


@pytest.mark.asyncio
async def test_project_requires_python_partial_minor_is_unknown() -> None:
    manifest = parse_pyproject(
        """
[project]
name = "demo-app"
requires-python = ">=3.11.5"
dependencies = ["demo"]
"""
    )

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.project_python.status is ProjectPythonStatus.INDETERMINATE

    assert result.severity is CheckSeverity.UNKNOWN


@pytest.mark.asyncio
async def test_missing_project_requires_python_is_not_a_failure() -> None:
    manifest = parse_pyproject(
        """
[project]
name = "demo-app"
dependencies = ["demo"]
"""
    )

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.project_python.status is ProjectPythonStatus.NOT_DECLARED

    assert result.project_python.severity is CheckSeverity.PASS

    assert result.severity is CheckSeverity.PASS


@pytest.mark.asyncio
async def test_dynamic_requires_python_is_unavailable() -> None:
    manifest = parse_pyproject(
        """
[project]
name = "demo-app"
dependencies = ["demo"]
dynamic = ["requires-python"]
"""
    )

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.project_python.status is ProjectPythonStatus.UNAVAILABLE

    assert result.severity is CheckSeverity.UNKNOWN


@pytest.mark.asyncio
async def test_problems_verbosity_hides_clean_passes() -> None:
    manifest = parse_requirements("alpha\nbeta\n")

    client = StubPyPIClient(
        {
            "alpha": _project(
                "alpha",
                (_wheel("alpha"),),
            ),
            "beta": _project(
                "beta",
                (_sdist("beta"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        verbosity=AuditVerbosity.PROBLEMS,
    )

    assert result.requirements_found == 2
    assert result.counts.passed == 1
    assert result.counts.warnings == 1

    assert [finding.requirement.name for finding in result.findings] == ["beta"]


@pytest.mark.asyncio
async def test_all_verbosity_includes_clean_passes() -> None:
    manifest = parse_requirements("alpha\nbeta\n")

    client = StubPyPIClient(
        {
            "alpha": _project(
                "alpha",
                (_wheel("alpha"),),
            ),
            "beta": _project(
                "beta",
                (_sdist("beta"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
        verbosity=AuditVerbosity.ALL,
    )

    assert [finding.requirement.name for finding in result.findings] == [
        "alpha",
        "beta",
    ]


@pytest.mark.asyncio
async def test_manifest_warning_makes_clean_audit_warn() -> None:
    manifest = parse_requirements("demo\ndemo\n")

    client = StubPyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await audit_manifest(
        manifest,
        _WIN_311,
        client,  # type: ignore[arg-type]
    )

    assert result.counts.manifest_warnings == 1
    assert result.severity is CheckSeverity.WARN


@pytest.mark.asyncio
async def test_invalid_concurrency_limit_is_rejected() -> None:
    manifest = parse_requirements("demo\n")

    client = StubPyPIClient({})

    with pytest.raises(
        ValueError,
        match="at least 1",
    ):
        await audit_manifest(
            manifest,
            _WIN_311,
            client,  # type: ignore[arg-type]
            max_concurrency=0,
        )
