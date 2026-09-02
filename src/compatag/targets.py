from __future__ import annotations

import re
from collections.abc import Iterable
from itertools import chain
from typing import Literal

from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from pydantic import BaseModel, ConfigDict, field_validator

_PYTHON_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)$")

_LINUX_PLATFORM_PATTERN = re.compile(
    r"^(?P<family>manylinux|musllinux)_"
    r"(?P<major>\d+)_(?P<minor>\d+)_(?P<arch>[a-z0-9_]+)$"
)

_MACOS_PLATFORM_PATTERN = re.compile(
    r"^macosx_(?P<major>\d+)_(?P<minor>\d+)_(?P<arch>x86_64|arm64)$"
)

_WINDOWS_PLATFORMS = frozenset(
    {
        "win32",
        "win_amd64",
        "win_arm64",
    }
)

_LINUX_ARCHITECTURES = frozenset(
    {
        "x86_64",
        "i686",
        "aarch64",
        "armv7l",
        "ppc64",
        "ppc64le",
        "s390x",
        "loongarch64",
        "riscv64",
    }
)

_MANYLINUX_LEGACY_ALIASES = {
    5: (
        "manylinux1",
        frozenset({"x86_64", "i686"}),
    ),
    12: (
        "manylinux2010",
        frozenset({"x86_64", "i686"}),
    ),
    17: (
        "manylinux2014",
        frozenset(
            {
                "x86_64",
                "i686",
                "aarch64",
                "armv7l",
                "ppc64",
                "ppc64le",
                "s390x",
            }
        ),
    ),
}


class TargetEnvironment(BaseModel):
    """A CPython environment whose wheel compatibility Compatag can evaluate."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    python_version: str
    implementation: Literal["cpython"] = "cpython"
    platform: str

    @field_validator("python_version")
    @classmethod
    def validate_python_version(cls, value: str) -> str:
        value = value.strip()
        match = _PYTHON_VERSION_PATTERN.fullmatch(value)

        if match is None:
            raise ValueError("python_version must use major.minor form, for example '3.11'")

        major = int(match.group("major"))
        minor = int(match.group("minor"))

        if major != 3 or minor < 9:
            raise ValueError("Compatag currently supports CPython 3.9 or newer target versions")

        return f"{major}.{minor}"

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        platform = value.strip().lower()
        _platform_tags(platform)
        return platform

    @property
    def version_info(self) -> tuple[int, int]:
        major, minor = self.python_version.split(".", maxsplit=1)
        return int(major), int(minor)


def compatibility_tags(target: TargetEnvironment) -> tuple[Tag, ...]:
    """Return wheel tags accepted by the target, ordered by preference."""

    platforms = _platform_tags(target.platform)
    python_version = target.version_info

    interpreter = f"cp{python_version[0]}{python_version[1]}"

    generated_tags = chain(
        cpython_tags(
            python_version=python_version,
            abis=[interpreter],
            platforms=platforms,
        ),
        compatible_tags(
            python_version=python_version,
            interpreter=interpreter,
            platforms=platforms,
        ),
    )

    return _ordered_unique(generated_tags)


def _platform_tags(platform: str) -> tuple[str, ...]:
    if platform in _WINDOWS_PLATFORMS:
        return (platform,)

    if platform.startswith("manylinux_"):
        return _manylinux_platforms(platform)

    if platform.startswith("musllinux_"):
        return _musllinux_platforms(platform)

    if platform.startswith("macosx_"):
        return _macos_platforms(platform)

    raise ValueError(
        "unsupported platform; expected a Windows, manylinux, musllinux, or macOS target"
    )


def _manylinux_platforms(platform: str) -> tuple[str, ...]:
    major, minor, architecture = _parse_linux_platform(platform, "manylinux")

    if major != 2:
        raise ValueError("Compatag currently models manylinux targets using glibc major version 2")

    floor = 5 if architecture in {"x86_64", "i686"} else 17

    if minor < floor:
        raise ValueError(f"{architecture} manylinux targets require glibc 2.{floor} or newer")

    platforms: list[str] = []

    for candidate_minor in range(minor, floor - 1, -1):
        platforms.append(f"manylinux_2_{candidate_minor}_{architecture}")

        alias = _MANYLINUX_LEGACY_ALIASES.get(candidate_minor)

        if alias is None:
            continue

        alias_name, alias_architectures = alias

        if architecture in alias_architectures:
            platforms.append(f"{alias_name}_{architecture}")

    return tuple(platforms)


def _musllinux_platforms(platform: str) -> tuple[str, ...]:
    major, minor, architecture = _parse_linux_platform(platform, "musllinux")

    if major < 1:
        raise ValueError("musllinux major version must be at least 1")

    return tuple(
        f"musllinux_{major}_{candidate_minor}_{architecture}"
        for candidate_minor in range(minor, -1, -1)
    )


def _macos_platforms(platform: str) -> tuple[str, ...]:
    match = _MACOS_PLATFORM_PATTERN.fullmatch(platform)

    if match is None:
        raise ValueError("macOS targets must look like 'macosx_14_0_arm64' or 'macosx_13_0_x86_64'")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    architecture = match.group("arch")

    if major < 10:
        raise ValueError("Compatag does not support macOS versions earlier than 10")

    if major >= 11 and minor != 0:
        raise ValueError(
            "macOS 11 and newer wheel targets use a zero minor version, "
            "for example 'macosx_14_0_arm64'"
        )

    return tuple(
        mac_platforms(
            version=(major, minor),
            arch=architecture,
        )
    )


def _parse_linux_platform(
    platform: str,
    expected_family: Literal["manylinux", "musllinux"],
) -> tuple[int, int, str]:
    match = _LINUX_PLATFORM_PATTERN.fullmatch(platform)

    if match is None or match.group("family") != expected_family:
        raise ValueError(
            f"{expected_family} targets must use the form "
            f"'{expected_family}_<major>_<minor>_<architecture>'"
        )

    architecture = match.group("arch")

    if architecture not in _LINUX_ARCHITECTURES:
        raise ValueError(f"unsupported Linux architecture '{architecture}'")

    return (
        int(match.group("major")),
        int(match.group("minor")),
        architecture,
    )


def _ordered_unique(tags: Iterable[Tag]) -> tuple[Tag, ...]:
    seen: set[Tag] = set()
    result: list[Tag] = []

    for tag in tags:
        if tag in seen:
            continue

        seen.add(tag)
        result.append(tag)

    return tuple(result)
