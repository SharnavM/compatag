from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pydantic import BaseModel, ConfigDict

from compatag.analyzer import (
    CheckSeverity,
    PackageCheckResult,
    check_package,
)
from compatag.manifests import (
    ManifestFormat,
    ManifestIssue,
    ManifestIssueCode,
    ManifestIssueSeverity,
    ManifestRequirement,
    ParsedManifest,
)
from compatag.pypi import PyPIClient
from compatag.python_compat import (
    PythonSupport,
    evaluate_requires_python,
)
from compatag.targets import TargetEnvironment


class AuditVerbosity(StrEnum):
    PROBLEMS = "problems"
    ALL = "all"


class ProjectPythonStatus(StrEnum):
    NOT_DECLARED = "not_declared"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    INDETERMINATE = "indeterminate"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class AuditCounts(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    passed: int = 0
    warnings: int = 0
    failures: int = 0
    unknown: int = 0

    manifest_warnings: int = 0
    manifest_errors: int = 0


class ProjectPythonCheck(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    specifier: str | None
    severity: CheckSeverity
    status: ProjectPythonStatus
    summary: str


class ManifestFinding(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    requirement: ManifestRequirement
    check: PackageCheckResult


class ManifestAuditResult(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    manifest_format: ManifestFormat
    project_name: str | None
    selected_extras: tuple[str, ...]

    target: TargetEnvironment

    manifest_complete: bool
    severity: CheckSeverity

    project_python: ProjectPythonCheck

    requirements_found: int
    unique_checks: int

    counts: AuditCounts

    findings: tuple[ManifestFinding, ...]
    issues: tuple[ManifestIssue, ...]

    verbosity: AuditVerbosity
    summary: str


@dataclass(frozen=True)
class _RequirementKey:
    name: str
    extras: tuple[str, ...]
    specifier: str
    marker: str | None
    url: str | None


async def audit_manifest(
    manifest: ParsedManifest,
    target: TargetEnvironment,
    pypi_client: PyPIClient,
    *,
    verbosity: AuditVerbosity = AuditVerbosity.PROBLEMS,
    max_concurrency: int = 8,
) -> ManifestAuditResult:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    project_python = _check_project_python(
        manifest,
        target,
    )

    unique_requirements = _unique_requirements(manifest.requirements)

    checks = await _run_package_checks(
        unique_requirements,
        target,
        pypi_client,
        max_concurrency=max_concurrency,
    )

    all_findings = tuple(
        _build_finding(
            requirement,
            checks[_requirement_key(requirement.text)],
        )
        for requirement in manifest.requirements
    )

    counts = _count_results(
        all_findings,
        manifest.issues,
    )

    severity = _overall_severity(
        counts,
        project_python,
    )

    findings = _select_findings(
        all_findings,
        verbosity,
    )

    return ManifestAuditResult(
        manifest_format=manifest.format,
        project_name=manifest.project_name,
        selected_extras=manifest.selected_extras,
        target=target,
        manifest_complete=manifest.is_complete,
        severity=severity,
        project_python=project_python,
        requirements_found=len(manifest.requirements),
        unique_checks=len(unique_requirements),
        counts=counts,
        findings=findings,
        issues=manifest.issues,
        verbosity=verbosity,
        summary=_build_summary(
            severity=severity,
            requirements_found=len(manifest.requirements),
            unique_checks=len(unique_requirements),
            counts=counts,
            manifest_complete=manifest.is_complete,
        ),
    )


def _requirement_key(
    text: str,
) -> _RequirementKey:
    requirement = Requirement(text)

    return _RequirementKey(
        name=str(canonicalize_name(requirement.name)),
        extras=tuple(sorted(str(canonicalize_name(extra)) for extra in requirement.extras)),
        specifier=str(requirement.specifier),
        marker=(str(requirement.marker) if requirement.marker is not None else None),
        url=requirement.url,
    )


def _unique_requirements(
    requirements: tuple[
        ManifestRequirement,
        ...,
    ],
) -> dict[_RequirementKey, str]:
    unique: dict[
        _RequirementKey,
        str,
    ] = {}

    for requirement in requirements:
        key = _requirement_key(requirement.text)

        unique.setdefault(
            key,
            requirement.text,
        )

    return unique


async def _run_package_checks(
    requirements: dict[
        _RequirementKey,
        str,
    ],
    target: TargetEnvironment,
    pypi_client: PyPIClient,
    *,
    max_concurrency: int,
) -> dict[
    _RequirementKey,
    PackageCheckResult,
]:
    semaphore = asyncio.Semaphore(max_concurrency)

    results: dict[
        _RequirementKey,
        PackageCheckResult,
    ] = {}

    async def run_check(
        key: _RequirementKey,
        requirement_text: str,
    ) -> None:
        async with semaphore:
            results[key] = await check_package(
                requirement_text,
                target,
                pypi_client,
            )

    async with asyncio.TaskGroup() as group:
        for key, requirement_text in requirements.items():
            group.create_task(
                run_check(
                    key,
                    requirement_text,
                )
            )

    return results


def _build_finding(
    requirement: ManifestRequirement,
    check: PackageCheckResult,
) -> ManifestFinding:
    if check.requirement != requirement.text:
        check = check.model_copy(update={"requirement": requirement.text})

    return ManifestFinding(
        requirement=requirement,
        check=check,
    )


def _check_project_python(
    manifest: ParsedManifest,
    target: TargetEnvironment,
) -> ProjectPythonCheck:
    issue_codes = {issue.code for issue in manifest.issues}

    unavailable_codes = {
        ManifestIssueCode.DYNAMIC_PROJECT_METADATA,
        ManifestIssueCode.INVALID_PROJECT_TABLE,
        ManifestIssueCode.DYNAMIC_REQUIRES_PYTHON,
    }

    if issue_codes & unavailable_codes:
        return ProjectPythonCheck(
            specifier=manifest.requires_python,
            severity=CheckSeverity.UNKNOWN,
            status=ProjectPythonStatus.UNAVAILABLE,
            summary=("The project's final Requires-Python constraint is not statically available."),
        )

    if ManifestIssueCode.INVALID_REQUIRES_PYTHON in issue_codes:
        return ProjectPythonCheck(
            specifier=manifest.requires_python,
            severity=CheckSeverity.UNKNOWN,
            status=ProjectPythonStatus.INVALID,
            summary=("The project's Requires-Python constraint is invalid."),
        )

    if manifest.requires_python is None:
        return ProjectPythonCheck(
            specifier=None,
            severity=CheckSeverity.PASS,
            status=ProjectPythonStatus.NOT_DECLARED,
            summary=("No project-level Requires-Python constraint applies from this manifest."),
        )

    result = evaluate_requires_python(
        manifest.requires_python,
        target,
    )

    if result.support is PythonSupport.COMPATIBLE:
        return ProjectPythonCheck(
            specifier=manifest.requires_python,
            severity=CheckSeverity.PASS,
            status=ProjectPythonStatus.COMPATIBLE,
            summary=(
                "The target Python release line satisfies the project's Requires-Python constraint."
            ),
        )

    if result.support is PythonSupport.INCOMPATIBLE:
        return ProjectPythonCheck(
            specifier=manifest.requires_python,
            severity=CheckSeverity.FAIL,
            status=ProjectPythonStatus.INCOMPATIBLE,
            summary=(
                f"CPython {target.python_version} "
                "does not satisfy the project's "
                f"Requires-Python constraint "
                f"'{manifest.requires_python}'."
            ),
        )

    if result.support is PythonSupport.INVALID:
        return ProjectPythonCheck(
            specifier=manifest.requires_python,
            severity=CheckSeverity.UNKNOWN,
            status=ProjectPythonStatus.INVALID,
            summary=(result.reason or "The project's Requires-Python constraint is invalid."),
        )

    return ProjectPythonCheck(
        specifier=manifest.requires_python,
        severity=CheckSeverity.UNKNOWN,
        status=ProjectPythonStatus.INDETERMINATE,
        summary=(
            result.reason or "The project's Requires-Python constraint could not be resolved."
        ),
    )


def _count_results(
    findings: tuple[
        ManifestFinding,
        ...,
    ],
    issues: tuple[
        ManifestIssue,
        ...,
    ],
) -> AuditCounts:
    passed = 0
    warnings = 0
    failures = 0
    unknown = 0

    for finding in findings:
        severity = finding.check.severity

        if severity is CheckSeverity.PASS:
            passed += 1
        elif severity is CheckSeverity.WARN:
            warnings += 1
        elif severity is CheckSeverity.FAIL:
            failures += 1
        else:
            unknown += 1

    manifest_warnings = sum(issue.severity is ManifestIssueSeverity.WARNING for issue in issues)

    manifest_errors = sum(issue.severity is ManifestIssueSeverity.ERROR for issue in issues)

    return AuditCounts(
        passed=passed,
        warnings=warnings,
        failures=failures,
        unknown=unknown,
        manifest_warnings=manifest_warnings,
        manifest_errors=manifest_errors,
    )


def _overall_severity(
    counts: AuditCounts,
    project_python: ProjectPythonCheck,
) -> CheckSeverity:
    if counts.failures > 0 or project_python.severity is CheckSeverity.FAIL:
        return CheckSeverity.FAIL

    if (
        counts.unknown > 0
        or counts.manifest_errors > 0
        or project_python.severity is CheckSeverity.UNKNOWN
    ):
        return CheckSeverity.UNKNOWN

    if (
        counts.warnings > 0
        or counts.manifest_warnings > 0
        or project_python.severity is CheckSeverity.WARN
    ):
        return CheckSeverity.WARN

    return CheckSeverity.PASS


def _select_findings(
    findings: tuple[
        ManifestFinding,
        ...,
    ],
    verbosity: AuditVerbosity,
) -> tuple[
    ManifestFinding,
    ...,
]:
    if verbosity is AuditVerbosity.ALL:
        return findings

    return tuple(
        finding
        for finding in findings
        if (finding.check.severity is not CheckSeverity.PASS or finding.check.notes)
    )


def _build_summary(
    *,
    severity: CheckSeverity,
    requirements_found: int,
    unique_checks: int,
    counts: AuditCounts,
    manifest_complete: bool,
) -> str:
    summary = (
        f"Audited {requirements_found} requirement "
        f"entries using {unique_checks} unique checks: "
        f"{counts.passed} pass, "
        f"{counts.warnings} warn, "
        f"{counts.failures} fail, "
        f"{counts.unknown} unknown. "
        f"Overall severity: {severity.value}."
    )

    if not manifest_complete:
        summary = (
            f"{summary} Manifest parsing is incomplete; "
            "only statically known requirements were audited."
        )

    return summary
