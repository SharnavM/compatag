from __future__ import annotations

import asyncio
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from compatag.analyzer import (
    CheckSeverity,
    PackageCheckResult,
    PackageCheckStatus,
)
from compatag.audit import (
    AuditCounts,
    AuditVerbosity,
    ManifestAuditResult,
    ProjectPythonCheck,
    audit_manifest,
)
from compatag.distributions import (
    DistributionFile,
    ProjectDistributions,
)
from compatag.manifests import (
    ManifestFormat,
    ManifestIssue,
    ManifestRequirement,
    ParsedManifest,
)
from compatag.pypi import ProjectSource
from compatag.targets import TargetEnvironment


class ComparisonImpact(StrEnum):
    UNCHANGED = "unchanged"
    IMPROVEMENT = "improvement"
    REGRESSION = "regression"
    INDETERMINATE = "indeterminate"


class ComparisonOutcome(StrEnum):
    UNCHANGED = "unchanged"
    IMPROVEMENT = "improvement"
    REGRESSION = "regression"
    MIXED = "mixed"
    INDETERMINATE = "indeterminate"


class ComparisonVerbosity(StrEnum):
    CHANGES = "changes"
    ALL = "all"


class RequirementComparison(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    requirement: ManifestRequirement

    from_check: PackageCheckResult
    to_check: PackageCheckResult

    impact: ComparisonImpact

    severity_changed: bool
    status_changed: bool
    selected_version_changed: bool
    artifact_changed: bool
    applicability_changed: bool


class ProjectPythonComparison(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    from_check: ProjectPythonCheck
    to_check: ProjectPythonCheck

    impact: ComparisonImpact
    status_changed: bool


class ComparisonCounts(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    unchanged: int = 0
    improvements: int = 0
    regressions: int = 0
    indeterminate: int = 0

    severity_changes: int = 0
    status_changes: int = 0
    selected_version_changes: int = 0
    artifact_changes: int = 0
    applicability_changes: int = 0


class TargetComparisonResult(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    manifest_format: ManifestFormat
    project_name: str | None
    selected_extras: tuple[str, ...]

    manifest_complete: bool
    issues: tuple[ManifestIssue, ...]

    from_target: TargetEnvironment
    to_target: TargetEnvironment

    from_severity: CheckSeverity
    to_severity: CheckSeverity

    from_counts: AuditCounts
    to_counts: AuditCounts

    outcome: ComparisonOutcome
    project_python: ProjectPythonComparison

    requirements_found: int
    unique_checks: int

    counts: ComparisonCounts
    comparisons: tuple[RequirementComparison, ...]

    verbosity: ComparisonVerbosity
    summary: str


class _MemoizedProjectSource:
    def __init__(
        self,
        source: ProjectSource,
    ) -> None:
        self._source = source
        self._tasks: dict[
            str,
            asyncio.Task[ProjectDistributions],
        ] = {}

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        task = self._tasks.get(name)

        if task is None:
            task = asyncio.create_task(self._source.get_project(name))

            self._tasks[name] = task

        return await task


_KNOWN_SEVERITY_RANK = {
    CheckSeverity.PASS: 0,
    CheckSeverity.WARN: 1,
    CheckSeverity.FAIL: 2,
}


async def compare_targets(
    manifest: ParsedManifest,
    from_target: TargetEnvironment,
    to_target: TargetEnvironment,
    project_source: ProjectSource,
    *,
    verbosity: ComparisonVerbosity = ComparisonVerbosity.CHANGES,
    max_concurrency: int = 8,
) -> TargetComparisonResult:
    cached_source = _MemoizedProjectSource(project_source)

    from_audit = await audit_manifest(
        manifest,
        from_target,
        cached_source,
        verbosity=AuditVerbosity.ALL,
        max_concurrency=max_concurrency,
    )

    to_audit = await audit_manifest(
        manifest,
        to_target,
        cached_source,
        verbosity=AuditVerbosity.ALL,
        max_concurrency=max_concurrency,
    )

    all_comparisons = tuple(
        _compare_finding_pair(
            from_finding.requirement,
            from_finding.check,
            to_finding.requirement,
            to_finding.check,
        )
        for from_finding, to_finding in zip(
            from_audit.findings,
            to_audit.findings,
            strict=True,
        )
    )

    project_python = _compare_project_python(
        from_audit.project_python,
        to_audit.project_python,
    )

    counts = _count_comparisons(all_comparisons)

    outcome = _comparison_outcome(
        counts,
        project_python,
        manifest_complete=manifest.is_complete,
    )

    comparisons = _select_comparisons(
        all_comparisons,
        verbosity,
    )

    return TargetComparisonResult(
        manifest_format=manifest.format,
        project_name=manifest.project_name,
        selected_extras=manifest.selected_extras,
        manifest_complete=manifest.is_complete,
        issues=manifest.issues,
        from_target=from_target,
        to_target=to_target,
        from_severity=from_audit.severity,
        to_severity=to_audit.severity,
        from_counts=from_audit.counts,
        to_counts=to_audit.counts,
        outcome=outcome,
        project_python=project_python,
        requirements_found=from_audit.requirements_found,
        unique_checks=from_audit.unique_checks,
        counts=counts,
        comparisons=comparisons,
        verbosity=verbosity,
        summary=_build_summary(
            outcome=outcome,
            requirements_found=from_audit.requirements_found,
            counts=counts,
            project_python=project_python,
            manifest_complete=manifest.is_complete,
        ),
    )


def _compare_finding_pair(
    from_requirement: ManifestRequirement,
    from_check: PackageCheckResult,
    to_requirement: ManifestRequirement,
    to_check: PackageCheckResult,
) -> RequirementComparison:
    if from_requirement != to_requirement:
        raise RuntimeError("target audits produced mismatched manifest requirement occurrences")

    from_artifact = _artifact_identity(from_check.artifact)

    to_artifact = _artifact_identity(to_check.artifact)

    return RequirementComparison(
        requirement=from_requirement,
        from_check=from_check,
        to_check=to_check,
        impact=_compare_severity(
            from_check.severity,
            to_check.severity,
        ),
        severity_changed=(from_check.severity is not to_check.severity),
        status_changed=(from_check.status is not to_check.status),
        selected_version_changed=(from_check.selected_version != to_check.selected_version),
        artifact_changed=(from_artifact != to_artifact),
        applicability_changed=(
            (from_check.status is PackageCheckStatus.NOT_APPLICABLE)
            != (to_check.status is PackageCheckStatus.NOT_APPLICABLE)
        ),
    )


def _artifact_identity(
    artifact: DistributionFile | None,
) -> tuple[str, str | None] | None:
    if artifact is None:
        return None

    return (
        artifact.filename,
        artifact.hashes.get("sha256"),
    )


def _compare_project_python(
    from_check: ProjectPythonCheck,
    to_check: ProjectPythonCheck,
) -> ProjectPythonComparison:
    return ProjectPythonComparison(
        from_check=from_check,
        to_check=to_check,
        impact=_compare_severity(
            from_check.severity,
            to_check.severity,
        ),
        status_changed=(from_check.status is not to_check.status),
    )


def _compare_severity(
    from_severity: CheckSeverity,
    to_severity: CheckSeverity,
) -> ComparisonImpact:
    if from_severity is CheckSeverity.UNKNOWN or to_severity is CheckSeverity.UNKNOWN:
        return ComparisonImpact.INDETERMINATE

    if from_severity is to_severity:
        return ComparisonImpact.UNCHANGED

    from_rank = _KNOWN_SEVERITY_RANK[from_severity]

    to_rank = _KNOWN_SEVERITY_RANK[to_severity]

    if to_rank < from_rank:
        return ComparisonImpact.IMPROVEMENT

    return ComparisonImpact.REGRESSION


def _count_comparisons(
    comparisons: tuple[
        RequirementComparison,
        ...,
    ],
) -> ComparisonCounts:
    unchanged = 0
    improvements = 0
    regressions = 0
    indeterminate = 0

    severity_changes = 0
    status_changes = 0
    selected_version_changes = 0
    artifact_changes = 0
    applicability_changes = 0

    for comparison in comparisons:
        if comparison.impact is ComparisonImpact.UNCHANGED:
            unchanged += 1
        elif comparison.impact is ComparisonImpact.IMPROVEMENT:
            improvements += 1
        elif comparison.impact is ComparisonImpact.REGRESSION:
            regressions += 1
        else:
            indeterminate += 1

        severity_changes += int(comparison.severity_changed)

        status_changes += int(comparison.status_changed)

        selected_version_changes += int(comparison.selected_version_changed)

        artifact_changes += int(comparison.artifact_changed)

        applicability_changes += int(comparison.applicability_changed)

    return ComparisonCounts(
        unchanged=unchanged,
        improvements=improvements,
        regressions=regressions,
        indeterminate=indeterminate,
        severity_changes=severity_changes,
        status_changes=status_changes,
        selected_version_changes=(selected_version_changes),
        artifact_changes=artifact_changes,
        applicability_changes=(applicability_changes),
    )


def _comparison_outcome(
    counts: ComparisonCounts,
    project_python: ProjectPythonComparison,
    *,
    manifest_complete: bool,
) -> ComparisonOutcome:
    impacts = {
        project_python.impact,
    }

    if counts.improvements:
        impacts.add(ComparisonImpact.IMPROVEMENT)

    if counts.regressions:
        impacts.add(ComparisonImpact.REGRESSION)

    if counts.indeterminate:
        impacts.add(ComparisonImpact.INDETERMINATE)

    has_improvement = ComparisonImpact.IMPROVEMENT in impacts

    has_regression = ComparisonImpact.REGRESSION in impacts

    has_uncertainty = ComparisonImpact.INDETERMINATE in impacts or not manifest_complete

    if has_improvement and has_regression:
        return ComparisonOutcome.MIXED

    if has_regression:
        return ComparisonOutcome.REGRESSION

    if has_improvement:
        if has_uncertainty:
            return ComparisonOutcome.INDETERMINATE

        return ComparisonOutcome.IMPROVEMENT

    if has_uncertainty:
        return ComparisonOutcome.INDETERMINATE

    return ComparisonOutcome.UNCHANGED


def _select_comparisons(
    comparisons: tuple[
        RequirementComparison,
        ...,
    ],
    verbosity: ComparisonVerbosity,
) -> tuple[
    RequirementComparison,
    ...,
]:
    if verbosity is ComparisonVerbosity.ALL:
        return comparisons

    return tuple(comparison for comparison in comparisons if _comparison_is_notable(comparison))


def _comparison_is_notable(
    comparison: RequirementComparison,
) -> bool:
    return (
        comparison.impact is not ComparisonImpact.UNCHANGED
        or comparison.status_changed
        or comparison.selected_version_changed
        or comparison.artifact_changed
        or comparison.applicability_changed
    )


def _build_summary(
    *,
    outcome: ComparisonOutcome,
    requirements_found: int,
    counts: ComparisonCounts,
    project_python: ProjectPythonComparison,
    manifest_complete: bool,
) -> str:
    summary = (
        f"Compared {requirements_found} requirement "
        f"entries: {counts.improvements} improved, "
        f"{counts.regressions} regressed, "
        f"{counts.unchanged} unchanged, "
        f"{counts.indeterminate} indeterminate. "
        f"Overall outcome: {outcome.value}."
    )

    changes: list[str] = []

    if counts.selected_version_changes:
        changes.append(f"{counts.selected_version_changes} selected version change(s)")

    if counts.artifact_changes:
        changes.append(f"{counts.artifact_changes} artifact change(s)")

    if counts.applicability_changes:
        changes.append(f"{counts.applicability_changes} applicability change(s)")

    if project_python.status_changed:
        changes.append("project Requires-Python status changed")

    if changes:
        summary = f"{summary} " + "; ".join(changes) + "."

    if not manifest_complete:
        summary = (
            f"{summary} The manifest is incomplete, "
            "so unknown dependencies may affect the "
            "comparison."
        )

    return summary
