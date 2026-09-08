from __future__ import annotations

import re
import tomllib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidName, canonicalize_name
from pydantic import BaseModel, ConfigDict


class ManifestFormat(StrEnum):
    REQUIREMENTS = "requirements"
    PYPROJECT = "pyproject"


class ManifestIssueSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class ManifestIssueCode(StrEnum):
    INVALID_REQUIREMENT = "invalid_requirement"
    UNSUPPORTED_DIRECTIVE = "unsupported_directive"
    UNSUPPORTED_ENTRY = "unsupported_entry"
    UNTERMINATED_CONTINUATION = "unterminated_continuation"
    DUPLICATE_REQUIREMENT = "duplicate_requirement"

    INVALID_TOML = "invalid_toml"
    DYNAMIC_PROJECT_METADATA = "dynamic_project_metadata"
    INVALID_PROJECT_TABLE = "invalid_project_table"
    INVALID_PROJECT_NAME = "invalid_project_name"
    INVALID_DYNAMIC = "invalid_dynamic"
    DYNAMIC_DEPENDENCIES = "dynamic_dependencies"
    DYNAMIC_OPTIONAL_DEPENDENCIES = "dynamic_optional_dependencies"
    DYNAMIC_REQUIRES_PYTHON = "dynamic_requires_python"
    INVALID_REQUIRES_PYTHON = "invalid_requires_python"
    INVALID_DEPENDENCIES = "invalid_dependencies"
    INVALID_OPTIONAL_DEPENDENCIES = "invalid_optional_dependencies"
    INVALID_EXTRA = "invalid_extra"
    UNKNOWN_OPTIONAL_GROUP = "unknown_optional_group"
    AMBIGUOUS_OPTIONAL_GROUP = "ambiguous_optional_group"
    UNSUPPORTED_SELF_REFERENCE = "unsupported_self_reference"


class ManifestRequirement(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    text: str
    name: str
    source: str

    line_start: int | None = None
    line_end: int | None = None


class ManifestIssue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    severity: ManifestIssueSeverity
    code: ManifestIssueCode

    message: str
    source: str

    line_start: int | None = None
    line_end: int | None = None

    value: str | None = None


class ParsedManifest(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    format: ManifestFormat

    project_name: str | None = None
    requires_python: str | None = None

    selected_extras: tuple[str, ...] = ()
    requirements: tuple[ManifestRequirement, ...] = ()
    issues: tuple[ManifestIssue, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not any(issue.severity is ManifestIssueSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class _LogicalLine:
    text: str
    line_start: int
    line_end: int


_WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def parse_requirements(
    text: str,
) -> ParsedManifest:
    requirements: list[ManifestRequirement] = []
    issues: list[ManifestIssue] = []
    seen: dict[str, str] = {}

    logical_lines, line_issues = _logical_lines(text)
    issues.extend(line_issues)

    for logical_line in logical_lines:
        entry = _strip_comment(logical_line.text).strip()

        if not entry:
            continue

        if entry.startswith("-"):
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=ManifestIssueCode.UNSUPPORTED_DIRECTIVE,
                message=("pip requirements-file directives are outside Compatag's initial scope."),
                source="requirements",
                line_start=logical_line.line_start,
                line_end=logical_line.line_end,
                value=entry,
            )
            continue

        if _looks_like_unnamed_entry(entry):
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=ManifestIssueCode.UNSUPPORTED_ENTRY,
                message=("Unnamed URLs and local paths are outside Compatag's PyPI-only scope."),
                source="requirements",
                line_start=logical_line.line_start,
                line_end=logical_line.line_end,
                value=entry,
            )
            continue

        requirement = _parse_requirement(
            entry,
            issues,
            source="requirements",
            line_start=logical_line.line_start,
            line_end=logical_line.line_end,
        )

        if requirement is None:
            continue

        _record_requirement(
            requirement,
            entry,
            requirements,
            issues,
            seen,
            source="requirements",
            line_start=logical_line.line_start,
            line_end=logical_line.line_end,
        )

    return ParsedManifest(
        format=ManifestFormat.REQUIREMENTS,
        requirements=tuple(requirements),
        issues=tuple(issues),
    )


def parse_pyproject(
    text: str,
    *,
    extras: Iterable[str] = (),
) -> ParsedManifest:
    issues: list[ManifestIssue] = []

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_TOML,
            message=(f"pyproject.toml could not be parsed: {exc}"),
            source="pyproject",
        )

        return ParsedManifest(
            format=ManifestFormat.PYPROJECT,
            issues=tuple(issues),
        )

    selected_extras = _normalize_requested_extras(
        extras,
        issues,
    )

    project_value = data.get("project")

    if project_value is None:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.DYNAMIC_PROJECT_METADATA,
            message=(
                "pyproject.toml has no [project] table, "
                "so standardized project dependencies "
                "are not statically available."
            ),
            source="project",
        )

        return ParsedManifest(
            format=ManifestFormat.PYPROJECT,
            selected_extras=selected_extras,
            issues=tuple(issues),
        )

    if not isinstance(project_value, dict):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_PROJECT_TABLE,
            message=("The 'project' key must be a TOML table."),
            source="project",
            value=repr(project_value),
        )

        return ParsedManifest(
            format=ManifestFormat.PYPROJECT,
            selected_extras=selected_extras,
            issues=tuple(issues),
        )

    project = cast(
        dict[str, object],
        project_value,
    )

    dynamic = _read_dynamic(
        project,
        issues,
    )

    project_name = _read_project_name(
        project,
        issues,
    )

    requires_python = _read_requires_python(
        project,
        dynamic,
        issues,
    )

    requirements: list[ManifestRequirement] = []
    seen: dict[str, str] = {}

    if "dependencies" in dynamic:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.DYNAMIC_DEPENDENCIES,
            message=(
                "project.dependencies is dynamic; "
                "statically declared dependencies may "
                "be incomplete because the build backend "
                "may append entries."
            ),
            source="project.dependencies",
        )

    _append_dependency_list(
        project.get("dependencies"),
        requirements,
        issues,
        seen,
        source="project.dependencies",
    )

    optional_groups = _read_optional_groups(
        project.get("optional-dependencies"),
        issues,
    )

    if selected_extras:
        if "optional-dependencies" in dynamic:
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.DYNAMIC_OPTIONAL_DEPENDENCIES),
                message=(
                    "project.optional-dependencies is "
                    "dynamic; selected extras may gain "
                    "additional dependencies during the build."
                ),
                source="project.optional-dependencies",
            )

        _append_optional_requirements(
            project_name,
            optional_groups,
            selected_extras,
            dynamic=("optional-dependencies" in dynamic),
            requirements=requirements,
            issues=issues,
            seen=seen,
        )

    return ParsedManifest(
        format=ManifestFormat.PYPROJECT,
        project_name=project_name,
        requires_python=requires_python,
        selected_extras=selected_extras,
        requirements=tuple(requirements),
        issues=tuple(issues),
    )


def _logical_lines(
    text: str,
) -> tuple[
    list[_LogicalLine],
    list[ManifestIssue],
]:
    logical_lines: list[_LogicalLine] = []
    issues: list[ManifestIssue] = []

    chunks: list[str] = []
    start_line: int | None = None

    for line_number, line in enumerate(
        text.splitlines(),
        start=1,
    ):
        if start_line is None:
            start_line = line_number

        if _has_line_continuation(line):
            chunks.append(line[:-1])
            continue

        chunks.append(line)

        logical_lines.append(
            _LogicalLine(
                text="".join(chunks),
                line_start=start_line,
                line_end=line_number,
            )
        )

        chunks.clear()
        start_line = None

    if chunks and start_line is not None:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=(ManifestIssueCode.UNTERMINATED_CONTINUATION),
            message=("The requirements file ends with an unterminated line continuation."),
            source="requirements",
            line_start=start_line,
            line_end=len(text.splitlines()),
            value="".join(chunks),
        )

    return logical_lines, issues


def _has_line_continuation(
    line: str,
) -> bool:
    trailing_backslashes = len(line) - len(line.rstrip("\\"))

    return trailing_backslashes % 2 == 1


def _strip_comment(
    text: str,
) -> str:
    single_quoted = False
    double_quoted = False
    escaped = False

    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue

        if character == "\\" and (single_quoted or double_quoted):
            escaped = True
            continue

        if character == "'" and not double_quoted:
            single_quoted = not single_quoted
            continue

        if character == '"' and not single_quoted:
            double_quoted = not double_quoted
            continue

        if (
            character == "#"
            and not single_quoted
            and not double_quoted
            and (index == 0 or text[index - 1].isspace())
        ):
            return text[:index]

    return text


def _looks_like_unnamed_entry(
    entry: str,
) -> bool:
    lowered = entry.lower()

    prefixes = (
        "http://",
        "https://",
        "file://",
        "git+",
        "hg+",
        "svn+",
        "bzr+",
        "./",
        "../",
        ".\\",
        "..\\",
        "/",
        "\\",
        "~",
    )

    return lowered.startswith(prefixes) or _WINDOWS_PATH_PATTERN.match(entry) is not None


def _parse_requirement(
    text: str,
    issues: list[ManifestIssue],
    *,
    source: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> Requirement | None:
    try:
        return Requirement(text)
    except InvalidRequirement as exc:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_REQUIREMENT,
            message=(f"Invalid dependency specifier: {exc}"),
            source=source,
            line_start=line_start,
            line_end=line_end,
            value=text,
        )

        return None


def _record_requirement(
    requirement: Requirement,
    text: str,
    requirements: list[ManifestRequirement],
    issues: list[ManifestIssue],
    seen: dict[str, str],
    *,
    source: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> None:
    key = str(requirement)
    first_source = seen.get(key)

    if first_source is not None:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.WARNING,
            code=ManifestIssueCode.DUPLICATE_REQUIREMENT,
            message=(f"The same requirement was already declared at {first_source}."),
            source=source,
            line_start=line_start,
            line_end=line_end,
            value=text,
        )
    else:
        seen[key] = source

    requirements.append(
        ManifestRequirement(
            text=text,
            name=str(canonicalize_name(requirement.name)),
            source=source,
            line_start=line_start,
            line_end=line_end,
        )
    )


def _read_dynamic(
    project: dict[str, object],
    issues: list[ManifestIssue],
) -> set[str]:
    value = project.get("dynamic")

    if value is None:
        return set()

    if not isinstance(value, list):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_DYNAMIC,
            message=("project.dynamic must be an array of strings."),
            source="project.dynamic",
            value=repr(value),
        )

        return set()

    dynamic: set[str] = set()

    for index, field in enumerate(value):
        if not isinstance(field, str):
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=ManifestIssueCode.INVALID_DYNAMIC,
                message=("Each project.dynamic entry must be a string."),
                source=(f"project.dynamic[{index}]"),
                value=repr(field),
            )
            continue

        dynamic.add(field)

    return dynamic


def _read_project_name(
    project: dict[str, object],
    issues: list[ManifestIssue],
) -> str | None:
    value = project.get("name")

    if not isinstance(value, str):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_PROJECT_NAME,
            message=("project.name must be statically defined as a valid project name."),
            source="project.name",
            value=(None if value is None else repr(value)),
        )

        return None

    try:
        return str(
            canonicalize_name(
                value,
                validate=True,
            )
        )
    except InvalidName as exc:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_PROJECT_NAME,
            message=(f"Invalid project name: {exc}"),
            source="project.name",
            value=value,
        )

        return None


def _read_requires_python(
    project: dict[str, object],
    dynamic: set[str],
    issues: list[ManifestIssue],
) -> str | None:
    value = project.get("requires-python")

    if "requires-python" in dynamic:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=(ManifestIssueCode.DYNAMIC_REQUIRES_PYTHON),
            message=(
                "project.requires-python is dynamic, "
                "so its final value cannot be "
                "established from pyproject.toml alone."
            ),
            source="project.requires-python",
            value=(None if value is None else repr(value)),
        )

    if value is None:
        return None

    if not isinstance(value, str):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=(ManifestIssueCode.INVALID_REQUIRES_PYTHON),
            message=("project.requires-python must be a version specifier string."),
            source="project.requires-python",
            value=repr(value),
        )

        return None

    try:
        SpecifierSet(value)
    except InvalidSpecifier as exc:
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=(ManifestIssueCode.INVALID_REQUIRES_PYTHON),
            message=(f"Invalid project.requires-python value: {exc}"),
            source="project.requires-python",
            value=value,
        )

    return value


def _append_dependency_list(
    value: object,
    requirements: list[ManifestRequirement],
    issues: list[ManifestIssue],
    seen: dict[str, str],
    *,
    source: str,
) -> None:
    if value is None:
        return

    if not isinstance(value, list):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=ManifestIssueCode.INVALID_DEPENDENCIES,
            message=(f"{source} must be an array of dependency strings."),
            source=source,
            value=repr(value),
        )

        return

    for index, item in enumerate(value):
        item_source = f"{source}[{index}]"

        if not isinstance(item, str):
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.INVALID_DEPENDENCIES),
                message=("Dependency entries must be strings."),
                source=item_source,
                value=repr(item),
            )
            continue

        requirement = _parse_requirement(
            item,
            issues,
            source=item_source,
        )

        if requirement is None:
            continue

        _record_requirement(
            requirement,
            item,
            requirements,
            issues,
            seen,
            source=item_source,
        )


def _normalize_requested_extras(
    extras: Iterable[str],
    issues: list[ManifestIssue],
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for value in extras:
        candidate = value.strip()

        try:
            extra = str(
                canonicalize_name(
                    candidate,
                    validate=True,
                )
            )
        except InvalidName as exc:
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=ManifestIssueCode.INVALID_EXTRA,
                message=(f"Invalid optional dependency group name: {exc}"),
                source="selected-extras",
                value=value,
            )
            continue

        if extra in seen:
            continue

        seen.add(extra)
        normalized.append(extra)

    return tuple(normalized)


def _read_optional_groups(
    value: object,
    issues: list[ManifestIssue],
) -> dict[str, tuple[str, object]]:
    if value is None:
        return {}

    if not isinstance(value, dict):
        _add_issue(
            issues,
            severity=ManifestIssueSeverity.ERROR,
            code=(ManifestIssueCode.INVALID_OPTIONAL_DEPENDENCIES),
            message=("project.optional-dependencies must be a table of dependency arrays."),
            source="project.optional-dependencies",
            value=repr(value),
        )

        return {}

    groups: dict[
        str,
        tuple[str, object],
    ] = {}

    for declared_name, group_value in cast(
        dict[str, object],
        value,
    ).items():
        try:
            normalized_name = str(
                canonicalize_name(
                    declared_name,
                    validate=True,
                )
            )
        except InvalidName as exc:
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.INVALID_OPTIONAL_DEPENDENCIES),
                message=(f"Invalid optional dependency group '{declared_name}': {exc}"),
                source=(f"project.optional-dependencies.{declared_name}"),
            )
            continue

        existing = groups.get(normalized_name)

        if existing is not None:
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.AMBIGUOUS_OPTIONAL_GROUP),
                message=(
                    "Optional dependency groups "
                    f"'{existing[0]}' and "
                    f"'{declared_name}' normalize to "
                    f"the same name "
                    f"'{normalized_name}'."
                ),
                source=("project.optional-dependencies"),
            )
            continue

        groups[normalized_name] = (
            declared_name,
            group_value,
        )

    return groups


def _append_optional_requirements(
    project_name: str | None,
    groups: dict[str, tuple[str, object]],
    selected_extras: tuple[str, ...],
    *,
    dynamic: bool,
    requirements: list[ManifestRequirement],
    issues: list[ManifestIssue],
    seen: dict[str, str],
) -> None:
    pending = deque(selected_extras)
    visited: set[str] = set()

    while pending:
        extra = pending.popleft()

        if extra in visited:
            continue

        visited.add(extra)

        group = groups.get(extra)

        if group is None:
            message = f"Optional dependency group '{extra}' is not declared statically."

            if dynamic:
                message = f"{message} The dynamic field may add it during the build."

            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.UNKNOWN_OPTIONAL_GROUP),
                message=message,
                source=(f"project.optional-dependencies.{extra}"),
            )
            continue

        declared_name, value = group

        source = f"project.optional-dependencies.{declared_name}"

        if not isinstance(value, list):
            _add_issue(
                issues,
                severity=ManifestIssueSeverity.ERROR,
                code=(ManifestIssueCode.INVALID_OPTIONAL_DEPENDENCIES),
                message=(f"{source} must be an array of dependency strings."),
                source=source,
                value=repr(value),
            )
            continue

        for index, item in enumerate(value):
            item_source = f"{source}[{index}]"

            if not isinstance(item, str):
                _add_issue(
                    issues,
                    severity=(ManifestIssueSeverity.ERROR),
                    code=(ManifestIssueCode.INVALID_OPTIONAL_DEPENDENCIES),
                    message=("Optional dependency entries must be strings."),
                    source=item_source,
                    value=repr(item),
                )
                continue

            requirement = _parse_requirement(
                item,
                issues,
                source=item_source,
            )

            if requirement is None:
                continue

            normalized_name = str(canonicalize_name(requirement.name))

            if project_name is not None and normalized_name == project_name:
                if (
                    requirement.url is None
                    and not str(requirement.specifier)
                    and requirement.marker is None
                    and requirement.extras
                ):
                    for nested_extra in sorted(requirement.extras):
                        pending.append(str(canonicalize_name(nested_extra)))

                    continue

                _add_issue(
                    issues,
                    severity=(ManifestIssueSeverity.ERROR),
                    code=(ManifestIssueCode.UNSUPPORTED_SELF_REFERENCE),
                    message=(
                        "Only simple self-references "
                        "used to compose optional "
                        "dependency groups are supported."
                    ),
                    source=item_source,
                    value=item,
                )
                continue

            _record_requirement(
                requirement,
                item,
                requirements,
                issues,
                seen,
                source=item_source,
            )


def _add_issue(
    issues: list[ManifestIssue],
    *,
    severity: ManifestIssueSeverity,
    code: ManifestIssueCode,
    message: str,
    source: str,
    line_start: int | None = None,
    line_end: int | None = None,
    value: str | None = None,
) -> None:
    issues.append(
        ManifestIssue(
            severity=severity,
            code=code,
            message=message,
            source=source,
            line_start=line_start,
            line_end=line_end,
            value=value,
        )
    )
