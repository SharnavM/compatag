import asyncio

import pytest

from compatag.compare import (
    ComparisonImpact,
    ComparisonOutcome,
    ComparisonVerbosity,
    compare_targets,
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
from compatag.targets import TargetEnvironment


def _wheel(
    name: str,
    *,
    version: str = "1.0",
    tag: str = "py3-none-any",
    requires_python: str | None = None,
) -> DistributionFile:
    filename = f"{name}-{version}-{tag}.whl"

    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.WHEEL,
        hashes={"sha256": f"digest-{filename}"},
        requires_python=requires_python,
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
        hashes={"sha256": f"digest-{filename}"},
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


class StubProjectSource:
    def __init__(
        self,
        projects: dict[
            str,
            ProjectDistributions,
        ],
        *,
        delay: float = 0.0,
    ) -> None:
        self.projects = projects
        self.delay = delay
        self.requests: list[str] = []

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        self.requests.append(name)

        if self.delay:
            await asyncio.sleep(self.delay)

        return self.projects[name]


_WIN_311 = TargetEnvironment(
    python_version="3.11",
    platform="win_amd64",
)

_LINUX_311 = TargetEnvironment(
    python_version="3.11",
    platform="manylinux_2_17_x86_64",
)

_WIN_312 = TargetEnvironment(
    python_version="3.12",
    platform="win_amd64",
)


@pytest.mark.asyncio
async def test_platform_wheel_change_does_not_imply_regression() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _wheel(
                        "demo",
                        tag=("cp311-cp311-manylinux_2_17_x86_64"),
                    ),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    assert result.outcome is ComparisonOutcome.UNCHANGED

    comparison = result.comparisons[0]

    assert comparison.impact is ComparisonImpact.UNCHANGED

    assert not comparison.severity_changed
    assert comparison.artifact_changed


@pytest.mark.asyncio
async def test_wheel_to_source_build_is_regression() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _sdist("demo"),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
    )

    assert result.outcome is ComparisonOutcome.REGRESSION

    comparison = result.comparisons[0]

    assert comparison.impact is ComparisonImpact.REGRESSION

    assert comparison.severity_changed


@pytest.mark.asyncio
async def test_source_build_to_wheel_is_improvement() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _sdist("demo"),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _LINUX_311,
        _WIN_311,
        source,
    )

    assert result.outcome is ComparisonOutcome.IMPROVEMENT

    assert result.comparisons[0].impact is ComparisonImpact.IMPROVEMENT


@pytest.mark.asyncio
async def test_improvement_and_regression_produce_mixed_outcome() -> None:
    manifest = parse_requirements("alpha\nbeta\n")

    source = StubProjectSource(
        {
            "alpha": _project(
                "alpha",
                (
                    _wheel(
                        "alpha",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _sdist("alpha"),
                ),
            ),
            "beta": _project(
                "beta",
                (
                    _wheel(
                        "beta",
                        tag=("cp311-cp311-manylinux_2_17_x86_64"),
                    ),
                    _sdist("beta"),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    assert result.outcome is ComparisonOutcome.MIXED

    assert result.counts.improvements == 1
    assert result.counts.regressions == 1


@pytest.mark.asyncio
async def test_unknown_result_makes_comparison_indeterminate() -> None:
    manifest = parse_requirements('demo; python_full_version >= "3.11.5"\n')

    source = StubProjectSource({})

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
    )

    assert result.outcome is ComparisonOutcome.INDETERMINATE

    assert result.counts.indeterminate == 1

    assert source.requests == []


@pytest.mark.asyncio
async def test_improvement_in_incomplete_manifest_remains_indeterminate() -> None:
    manifest = parse_requirements("demo\n-r private.txt\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _sdist("demo"),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _LINUX_311,
        _WIN_311,
        source,
    )

    assert not result.manifest_complete

    assert result.outcome is ComparisonOutcome.INDETERMINATE


@pytest.mark.asyncio
async def test_regression_in_incomplete_manifest_is_still_regression() -> None:
    manifest = parse_requirements("demo\n-r private.txt\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _sdist("demo"),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
    )

    assert result.outcome is ComparisonOutcome.REGRESSION


@pytest.mark.asyncio
async def test_project_requires_python_can_regress() -> None:
    manifest = parse_pyproject(
        """
[project]
name = "demo-app"
requires-python = ">=3.11,<3.12"
dependencies = ["demo"]
"""
    )

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _WIN_312,
        source,
    )

    assert result.project_python.impact is ComparisonImpact.REGRESSION

    assert result.outcome is ComparisonOutcome.REGRESSION


@pytest.mark.asyncio
async def test_applicability_change_is_recorded_without_severity_regression() -> None:
    manifest = parse_requirements('demo; sys_platform == "win32"\n')

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    comparison = result.comparisons[0]

    assert comparison.impact is ComparisonImpact.UNCHANGED

    assert comparison.status_changed
    assert comparison.applicability_changed

    assert result.outcome is ComparisonOutcome.UNCHANGED


@pytest.mark.asyncio
async def test_selected_version_change_is_recorded_without_severity_change() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        version="1.0",
                        requires_python=">=3.10",
                    ),
                    _wheel(
                        "demo",
                        version="2.0",
                        requires_python=">=3.12",
                    ),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _WIN_312,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    comparison = result.comparisons[0]

    assert comparison.impact is ComparisonImpact.UNCHANGED

    assert comparison.selected_version_changed
    assert comparison.artifact_changed

    assert comparison.from_check.selected_version == "1.0"

    assert comparison.to_check.selected_version == "2.0"


@pytest.mark.asyncio
async def test_project_metadata_is_requested_once_across_both_targets() -> None:
    manifest = parse_requirements("demo>=1\ndemo<3\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        },
        delay=0.01,
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    assert result.unique_checks == 2

    assert source.requests == ["demo"]


@pytest.mark.asyncio
async def test_changes_verbosity_hides_identical_clean_result() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.CHANGES,
    )

    assert result.requirements_found == 1
    assert result.counts.unchanged == 1

    assert result.comparisons == ()


@pytest.mark.asyncio
async def test_all_verbosity_keeps_identical_clean_result() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    assert len(result.comparisons) == 1

    assert result.comparisons[0].impact is ComparisonImpact.UNCHANGED


@pytest.mark.asyncio
async def test_comparison_order_follows_manifest_order() -> None:
    manifest = parse_requirements("alpha\nbeta\ngamma\n")

    source = StubProjectSource(
        {
            name: _project(
                name,
                (_wheel(name),),
            )
            for name in (
                "alpha",
                "beta",
                "gamma",
            )
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
        verbosity=ComparisonVerbosity.ALL,
    )

    assert [comparison.requirement.name for comparison in result.comparisons] == [
        "alpha",
        "beta",
        "gamma",
    ]


@pytest.mark.asyncio
async def test_counts_track_operational_changes_separately() -> None:
    manifest = parse_requirements("demo\n")

    source = StubProjectSource(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag="cp311-cp311-win_amd64",
                    ),
                    _wheel(
                        "demo",
                        tag=("cp311-cp311-manylinux_2_17_x86_64"),
                    ),
                ),
            ),
        }
    )

    result = await compare_targets(
        manifest,
        _WIN_311,
        _LINUX_311,
        source,
    )

    assert result.counts.unchanged == 1
    assert result.counts.regressions == 0
    assert result.counts.improvements == 0

    assert result.counts.severity_changes == 0
    assert result.counts.artifact_changes == 1
