from dataclasses import dataclass
from enum import StrEnum

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from compatag.targets import TargetEnvironment


class PythonSupport(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    INDETERMINATE = "indeterminate"
    INVALID = "invalid"


@dataclass(frozen=True)
class PythonCompatibility:
    support: PythonSupport
    reason: str | None = None


def evaluate_requires_python(
    requires_python: str | None,
    target: TargetEnvironment,
) -> PythonCompatibility:
    if requires_python is None:
        return PythonCompatibility(
            support=PythonSupport.COMPATIBLE,
        )

    try:
        requirement = SpecifierSet(requires_python)
    except InvalidSpecifier as exc:
        return PythonCompatibility(
            support=PythonSupport.INVALID,
            reason=(f"Invalid Requires-Python metadata '{requires_python}': {exc}"),
        )

    major, minor = target.version_info

    target_minor = SpecifierSet(f">={major}.{minor},<{major}.{minor + 1}")

    try:
        if target_minor.is_subset(requirement):
            return PythonCompatibility(
                support=PythonSupport.COMPATIBLE,
            )

        if target_minor.is_disjoint(requirement):
            return PythonCompatibility(
                support=PythonSupport.INCOMPATIBLE,
            )
    except ValueError as exc:
        return PythonCompatibility(
            support=PythonSupport.INDETERMINATE,
            reason=(
                f"Requires-Python could not be compared against the target minor version: {exc}"
            ),
        )

    return PythonCompatibility(
        support=PythonSupport.INDETERMINATE,
        reason=(
            f"Requires-Python '{requires_python}' matches only part "
            f"of the CPython {target.python_version} release line; "
            "a target micro version is required."
        ),
    )
