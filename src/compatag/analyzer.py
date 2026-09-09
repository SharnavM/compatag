from __future__ import annotations

import io
import token
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from packaging.markers import (
    Marker,
    UndefinedComparison,
    UndefinedEnvironmentName,
)
from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, create_compatible_tags_selector
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

from compatag.distributions import (
    DistributionFile,
    DistributionKind,
    ProjectDistributions,
)
from compatag.pypi import (
    ProjectNotFoundError,
    PyPIClient,
    PyPIRequestError,
    PyPIResponseError,
)
from compatag.python_compat import (
    PythonCompatibility,
    PythonSupport,
    evaluate_requires_python,
)
from compatag.targets import TargetEnvironment, compatibility_tags


class CheckSeverity(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class PackageCheckStatus(StrEnum):
    WHEEL_AVAILABLE = "wheel_available"
    UNIVERSAL_WHEEL_AVAILABLE = "universal_wheel_available"
    NOT_APPLICABLE = "not_applicable"
    SOURCE_BUILD_REQUIRED = "source_build_required"

    PROJECT_NOT_FOUND = "project_not_found"
    NO_MATCHING_RELEASE = "no_matching_release"
    NO_COMPATIBLE_DISTRIBUTION = "no_compatible_distribution"
    YANKED_ONLY = "yanked_only"

    UNSUPPORTED_REQUIREMENT = "unsupported_requirement"
    INDETERMINATE_MARKER = "indeterminate_marker"
    INDETERMINATE_REQUIRES_PYTHON = "indeterminate_requires_python"
    METADATA_ERROR = "metadata_error"
    NETWORK_ERROR = "network_error"


class PackageCheckResult(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    requirement: str
    package: str | None
    target: TargetEnvironment

    severity: CheckSeverity
    status: PackageCheckStatus

    selected_version: str | None = None
    artifact: DistributionFile | None = None

    summary: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _WheelCandidate:
    file: DistributionFile
    tags: frozenset[Tag]


@dataclass(frozen=True)
class _Uncertainty:
    status: PackageCheckStatus
    reason: str
    artifact: DistributionFile | None = None


@dataclass(frozen=True)
class _ReleaseEvaluation:
    wheel: _WheelCandidate | None = None
    sdist: DistributionFile | None = None
    uncertainty: _Uncertainty | None = None


_MARKER_VARIABLES = frozenset(
    {
        "implementation_name",
        "implementation_version",
        "os_name",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_full_version",
        "python_version",
        "sys_platform",
        "extra",
        "extras",
        "dependency_groups",
    }
)

_INDETERMINATE_MARKER_VARIABLES = frozenset(
    {
        "implementation_version",
        "python_full_version",
        "platform_release",
        "platform_version",
        "extra",
        "extras",
        "dependency_groups",
    }
)

_LINUX_ARCHITECTURES = (
    "loongarch64",
    "aarch64",
    "ppc64le",
    "ppc64",
    "s390x",
    "riscv64",
    "armv7l",
    "x86_64",
    "i686",
)


async def check_package(
    requirement_text: str,
    target: TargetEnvironment,
    pypi_client: PyPIClient,
) -> PackageCheckResult:
    requirement_text = requirement_text.strip()

    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement as exc:
        return _result(
            requirement=requirement_text,
            package=None,
            target=target,
            severity=CheckSeverity.UNKNOWN,
            status=PackageCheckStatus.UNSUPPORTED_REQUIREMENT,
            summary="The requirement could not be parsed.",
            notes=(str(exc),),
        )

    package = str(canonicalize_name(requirement.name))
    notes = _requirement_notes(requirement)

    if requirement.url is not None:
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.UNKNOWN,
            status=PackageCheckStatus.UNSUPPORTED_REQUIREMENT,
            summary="Direct URL requirements are outside Compatag's PyPI analysis scope.",
            notes=notes,
        )

    if any(specifier.operator == "===" for specifier in requirement.specifier):
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.UNKNOWN,
            status=PackageCheckStatus.UNSUPPORTED_REQUIREMENT,
            summary="Arbitrary equality requirements using '===' are not supported.",
            notes=notes,
        )

    if requirement.marker is not None:
        marker_result, marker_reason = _evaluate_marker(
            requirement.marker,
            target,
        )

        if marker_result is None:
            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.UNKNOWN,
                status=PackageCheckStatus.INDETERMINATE_MARKER,
                summary="The environment marker cannot be resolved from this target.",
                notes=_append_note(notes, marker_reason),
            )

        if not marker_result:
            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.PASS,
                status=PackageCheckStatus.NOT_APPLICABLE,
                summary="The requirement does not apply to this target environment.",
                notes=notes,
            )

    try:
        project = await pypi_client.get_project(package)
    except ProjectNotFoundError:
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.FAIL,
            status=PackageCheckStatus.PROJECT_NOT_FOUND,
            summary=f"Project '{package}' was not found on PyPI.",
            notes=notes,
        )
    except PyPIRequestError as exc:
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.UNKNOWN,
            status=PackageCheckStatus.NETWORK_ERROR,
            summary="PyPI could not be queried reliably.",
            notes=_append_note(notes, str(exc)),
        )
    except PyPIResponseError as exc:
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.UNKNOWN,
            status=PackageCheckStatus.METADATA_ERROR,
            summary="PyPI returned project metadata that Compatag could not interpret.",
            notes=_append_note(notes, str(exc)),
        )

    project_notes = _project_notes(project)
    notes = (*notes, *project_notes)

    versions = _matching_versions(
        project,
        requirement,
    )

    if not versions:
        return _result(
            requirement=requirement_text,
            package=package,
            target=target,
            severity=CheckSeverity.FAIL,
            status=PackageCheckStatus.NO_MATCHING_RELEASE,
            summary="No published release satisfies the requested version constraint.",
            notes=notes,
        )

    files_by_version = _group_files_by_version(project)

    for version in versions:
        evaluation = _evaluate_release(
            files_by_version.get(version, ()),
            target,
            yanked=False,
        )

        if evaluation.wheel is not None:
            wheel = evaluation.wheel

            status = (
                PackageCheckStatus.UNIVERSAL_WHEEL_AVAILABLE
                if _is_universal_wheel(wheel.tags)
                else PackageCheckStatus.WHEEL_AVAILABLE
            )

            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.PASS,
                status=status,
                selected_version=str(version),
                artifact=wheel.file,
                summary="A compatible wheel is available.",
                notes=notes,
            )

        if evaluation.uncertainty is not None:
            uncertainty = evaluation.uncertainty

            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.UNKNOWN,
                status=uncertainty.status,
                selected_version=str(version),
                artifact=uncertainty.artifact,
                summary=uncertainty.reason,
                notes=notes,
            )

        if evaluation.sdist is not None:
            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.WARN,
                status=PackageCheckStatus.SOURCE_BUILD_REQUIRED,
                selected_version=str(version),
                artifact=evaluation.sdist,
                summary=(
                    "No compatible wheel is available for the selected release, "
                    "but a source distribution is available."
                ),
                notes=notes,
            )

    for version in versions:
        evaluation = _evaluate_release(
            files_by_version.get(version, ()),
            target,
            yanked=True,
        )

        artifact: DistributionFile | None = None

        if evaluation.wheel is not None:
            artifact = evaluation.wheel.file
        elif evaluation.sdist is not None:
            artifact = evaluation.sdist

        if artifact is not None:
            yank_notes = notes

            if artifact.yanked_reason is not None:
                yank_notes = _append_note(
                    yank_notes,
                    f"Yanked reason: {artifact.yanked_reason}",
                )

            return _result(
                requirement=requirement_text,
                package=package,
                target=target,
                severity=CheckSeverity.FAIL,
                status=PackageCheckStatus.YANKED_ONLY,
                selected_version=str(version),
                artifact=artifact,
                summary=(
                    "An otherwise usable distribution exists, but the published artifact is yanked."
                ),
                notes=yank_notes,
            )

    return _result(
        requirement=requirement_text,
        package=package,
        target=target,
        severity=CheckSeverity.FAIL,
        status=PackageCheckStatus.NO_COMPATIBLE_DISTRIBUTION,
        summary=(
            "Matching releases exist, but none provide a usable wheel "
            "or source distribution for this target."
        ),
        notes=notes,
    )


def _result(
    *,
    requirement: str,
    package: str | None,
    target: TargetEnvironment,
    severity: CheckSeverity,
    status: PackageCheckStatus,
    summary: str,
    selected_version: str | None = None,
    artifact: DistributionFile | None = None,
    notes: tuple[str, ...] = (),
) -> PackageCheckResult:
    return PackageCheckResult(
        requirement=requirement,
        package=package,
        target=target,
        severity=severity,
        status=status,
        selected_version=selected_version,
        artifact=artifact,
        summary=summary,
        notes=notes,
    )


def _requirement_notes(
    requirement: Requirement,
) -> tuple[str, ...]:
    if not requirement.extras:
        return ()

    extras = ", ".join(sorted(requirement.extras))

    return (
        (
            f"Requested extras ({extras}) are not resolved; "
            f"this check covers only the '{requirement.name}' distribution."
        ),
    )


def _project_notes(
    project: ProjectDistributions,
) -> tuple[str, ...]:
    if project.status == "active":
        return ()

    note = f"PyPI project status: {project.status}."

    if project.status_reason:
        note = f"{note} {project.status_reason}"

    return (note,)


def _append_note(
    notes: tuple[str, ...],
    note: str | None,
) -> tuple[str, ...]:
    if not note:
        return notes

    return (*notes, note)


def _evaluate_marker(
    marker: Marker,
    target: TargetEnvironment,
) -> tuple[bool | None, str | None]:
    variables = _marker_variables(marker)

    unresolved = sorted(variables & _INDETERMINATE_MARKER_VARIABLES)

    if unresolved:
        names = ", ".join(unresolved)

        return (
            None,
            (
                "The target does not contain enough information "
                f"to evaluate marker variable(s): {names}."
            ),
        )

    try:
        applies = marker.evaluate(
            environment=_marker_environment(target),
            context="requirement",
        )
    except (
        UndefinedComparison,
        UndefinedEnvironmentName,
    ) as exc:
        return None, str(exc)

    return applies, None


def _marker_variables(
    marker: Marker,
) -> set[str]:
    stream = io.StringIO(str(marker)).readline

    return {
        item.string
        for item in tokenize.generate_tokens(stream)
        if item.type == token.NAME and item.string in _MARKER_VARIABLES
    }


def _marker_environment(
    target: TargetEnvironment,
) -> dict[str, str]:
    platform = target.platform

    if platform.startswith("win"):
        os_name = "nt"
        sys_platform = "win32"
        platform_system = "Windows"
    elif platform.startswith("macosx_"):
        os_name = "posix"
        sys_platform = "darwin"
        platform_system = "Darwin"
    else:
        os_name = "posix"
        sys_platform = "linux"
        platform_system = "Linux"

    return {
        "implementation_name": "cpython",
        "implementation_version": f"{target.python_version}.0",
        "os_name": os_name,
        "platform_machine": _platform_machine(platform),
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": platform_system,
        "platform_version": "",
        "python_full_version": f"{target.python_version}.0",
        "python_version": target.python_version,
        "sys_platform": sys_platform,
    }


def _platform_machine(
    platform: str,
) -> str:
    if platform == "win_amd64":
        return "AMD64"

    if platform == "win_arm64":
        return "ARM64"

    if platform == "win32":
        return "x86"

    if platform.endswith("_arm64"):
        return "arm64"

    for architecture in _LINUX_ARCHITECTURES:
        if platform.endswith(f"_{architecture}"):
            return architecture

    raise ValueError(f"could not determine platform machine for '{platform}'")


def _matching_versions(
    project: ProjectDistributions,
    requirement: Requirement,
) -> list[Version]:
    published_versions: set[Version] = set()

    for version_text in project.versions:
        try:
            published_versions.add(Version(version_text))
        except InvalidVersion:
            continue

    for file in project.files:
        if file.version is None:
            continue

        try:
            published_versions.add(Version(file.version))
        except InvalidVersion:
            continue

    matching = requirement.specifier.filter(published_versions)

    return sorted(
        set(matching),
        reverse=True,
    )


def _group_files_by_version(
    project: ProjectDistributions,
) -> dict[Version, tuple[DistributionFile, ...]]:
    grouped: dict[
        Version,
        list[DistributionFile],
    ] = defaultdict(list)

    for file in project.files:
        if file.version is None:
            continue

        try:
            version = Version(file.version)
        except InvalidVersion:
            continue

        grouped[version].append(file)

    return {version: tuple(files) for version, files in grouped.items()}


def _evaluate_release(
    files: tuple[DistributionFile, ...],
    target: TargetEnvironment,
    *,
    yanked: bool,
) -> _ReleaseEvaluation:
    target_tags = compatibility_tags(target)
    target_tag_set = set(target_tags)

    wheels: list[_WheelCandidate] = []

    wheel_uncertainty: _Uncertainty | None = None
    sdist_uncertainty: _Uncertainty | None = None

    sdists: list[DistributionFile] = []

    for file in files:
        if file.yanked is not yanked:
            continue

        if file.kind is DistributionKind.WHEEL:
            try:
                _, _, _, wheel_tags = parse_wheel_filename(file.filename)
            except InvalidWheelFilename as exc:
                if wheel_uncertainty is None:
                    wheel_uncertainty = _Uncertainty(
                        status=PackageCheckStatus.METADATA_ERROR,
                        reason=(f"A published wheel filename could not be parsed reliably: {exc}"),
                        artifact=file,
                    )

                continue

            if wheel_tags.isdisjoint(target_tag_set):
                continue

            python_check = evaluate_requires_python(
                file.requires_python,
                target,
            )

            if python_check.support is PythonSupport.COMPATIBLE:
                wheels.append(
                    _WheelCandidate(
                        file=file,
                        tags=wheel_tags,
                    )
                )
            elif python_check.support in {
                PythonSupport.INDETERMINATE,
                PythonSupport.INVALID,
            }:
                if wheel_uncertainty is None:
                    wheel_uncertainty = _python_uncertainty(
                        file,
                        python_check,
                    )

            continue

        if file.kind is DistributionKind.SDIST:
            python_check = evaluate_requires_python(
                file.requires_python,
                target,
            )

            if python_check.support is PythonSupport.COMPATIBLE:
                sdists.append(file)
            elif python_check.support in {
                PythonSupport.INDETERMINATE,
                PythonSupport.INVALID,
            }:
                if sdist_uncertainty is None:
                    sdist_uncertainty = _python_uncertainty(
                        file,
                        python_check,
                    )

    if wheels:
        selector = create_compatible_tags_selector(target_tags)

        selected = next(
            selector(
                (
                    candidate,
                    candidate.tags,
                )
                for candidate in wheels
            )
        )

        return _ReleaseEvaluation(wheel=selected)

    if wheel_uncertainty is not None:
        return _ReleaseEvaluation(uncertainty=wheel_uncertainty)

    if sdists:
        selected_sdist = min(
            sdists,
            key=lambda file: file.filename.lower(),
        )

        return _ReleaseEvaluation(sdist=selected_sdist)

    if sdist_uncertainty is not None:
        return _ReleaseEvaluation(uncertainty=sdist_uncertainty)

    return _ReleaseEvaluation()


def _python_uncertainty(
    file: DistributionFile,
    python_check: PythonCompatibility,
) -> _Uncertainty:
    status = (
        PackageCheckStatus.METADATA_ERROR
        if python_check.support is PythonSupport.INVALID
        else PackageCheckStatus.INDETERMINATE_REQUIRES_PYTHON
    )

    return _Uncertainty(
        status=status,
        reason=(python_check.reason or "Requires-Python could not be evaluated."),
        artifact=file,
    )


def _is_universal_wheel(
    tags: frozenset[Tag],
) -> bool:
    return any(tag.abi == "none" and tag.platform == "any" for tag in tags)
