from __future__ import annotations

import tarfile
import tomllib
import zipfile
from configparser import ConfigParser
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import (
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
PYPROJECT = ROOT / "pyproject.toml"


def main() -> int:
    project = _project_metadata()

    project_name = str(canonicalize_name(project["name"]))

    project_version = project["version"]

    wheels = sorted(DIST_DIR.glob("*.whl"))

    sdists = sorted(DIST_DIR.glob("*.tar.gz"))

    if len(wheels) != 1:
        _fail(f"expected exactly one wheel in dist, found {len(wheels)}")

    if len(sdists) != 1:
        _fail(f"expected exactly one source distribution in dist, found {len(sdists)}")

    _verify_wheel(
        wheels[0],
        project_name,
        project_version,
        project,
    )

    _verify_sdist(
        sdists[0],
        project_name,
        project_version,
    )

    print("Release artifacts verified:")

    print(f"  wheel: {wheels[0].name}")

    print(f"  sdist: {sdists[0].name}")

    return 0


def _project_metadata() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        document = tomllib.load(handle)

    project = document.get("project")

    if not isinstance(project, dict):
        _fail("pyproject.toml has no [project] table")

    return project


def _verify_wheel(
    wheel: Path,
    expected_name: str,
    expected_version: str,
    project: dict[str, object],
) -> None:
    (
        distribution_name,
        version,
        build,
        tags,
    ) = parse_wheel_filename(wheel.name)

    if str(distribution_name) != expected_name:
        _fail(f"wheel project name does not match pyproject.toml: {distribution_name}")

    if str(version) != expected_version:
        _fail(f"wheel version does not match pyproject.toml: {version}")

    if build:
        _fail(f"unexpected wheel build tag: {build}")

    expected_tags = frozenset(
        {
            Tag(
                "py3",
                "none",
                "any",
            )
        }
    )

    if tags != expected_tags:
        _fail(f"expected a py3-none-any wheel, found tags: {sorted(map(str, tags))}")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

        metadata_path = _single_member(
            names,
            ".dist-info/METADATA",
        )

        dist_info = metadata_path.rsplit(
            "/",
            1,
        )[0]

        entry_points_path = f"{dist_info}/entry_points.txt"

        required_members = {
            "compatag/__init__.py",
            "compatag/cli.py",
            "compatag/mcp_server.py",
            metadata_path,
            f"{dist_info}/WHEEL",
            entry_points_path,
        }

        missing_members = required_members - names

        if missing_members:
            _fail("wheel is missing expected files: " + ", ".join(sorted(missing_members)))

        metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_path))

        _verify_core_metadata(
            metadata,
            expected_name,
            expected_version,
            project,
        )

        _verify_entry_points(archive.read(entry_points_path).decode("utf-8"))


def _verify_core_metadata(
    metadata,
    expected_name: str,
    expected_version: str,
    project: dict[str, object],
) -> None:
    metadata_name = str(canonicalize_name(metadata["Name"]))

    if metadata_name != expected_name:
        _fail(f"wheel metadata has unexpected project name: {metadata_name}")

    if metadata["Version"] != expected_version:
        _fail(f"wheel metadata has unexpected version: {metadata['Version']}")

    expected_python = project.get("requires-python")

    if metadata["Requires-Python"] != expected_python:
        _fail("wheel Requires-Python does not match pyproject.toml")

    expected_license = project.get("license")

    if metadata["License-Expression"] != expected_license:
        _fail("wheel License-Expression does not match pyproject.toml")

    expected_requirements = {
        str(Requirement(requirement)) for requirement in project.get("dependencies", [])
    }

    metadata_requirements = {
        str(Requirement(requirement))
        for requirement in metadata.get_all(
            "Requires-Dist",
            [],
        )
    }

    missing_requirements = expected_requirements - metadata_requirements

    if missing_requirements:
        _fail(
            "wheel metadata is missing runtime "
            "requirements: " + ", ".join(sorted(missing_requirements))
        )


def _verify_entry_points(
    contents: str,
) -> None:
    parser = ConfigParser()

    parser.read_string(contents)

    if not parser.has_section("console_scripts"):
        _fail("wheel has no console_scripts entry-point group")

    scripts = dict(parser["console_scripts"])

    expected = {
        "compatag": "compatag.cli:main",
        "compatag-mcp": ("compatag.mcp_server:main"),
    }

    for name, target in expected.items():
        if scripts.get(name) != target:
            _fail(f"console script '{name}' does not point to '{target}'")


def _verify_sdist(
    sdist: Path,
    expected_name: str,
    expected_version: str,
) -> None:
    distribution_name, version = parse_sdist_filename(sdist.name)

    if str(distribution_name) != expected_name:
        _fail(f"sdist project name does not match pyproject.toml: {distribution_name}")

    if str(version) != expected_version:
        _fail(f"sdist version does not match pyproject.toml: {version}")

    root = f"{expected_name}-{expected_version}"

    required_members = {
        f"{root}/LICENSE",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/PKG-INFO",
        f"{root}/src/compatag/__init__.py",
        f"{root}/src/compatag/cli.py",
        f"{root}/src/compatag/mcp_server.py",
    }

    with tarfile.open(
        sdist,
        mode="r:gz",
    ) as archive:
        names = {member.name for member in archive.getmembers()}

    missing_members = required_members - names

    if missing_members:
        _fail("sdist is missing expected files: " + ", ".join(sorted(missing_members)))


def _single_member(
    names: set[str],
    suffix: str,
) -> str:
    matches = [name for name in names if name.endswith(suffix)]

    if len(matches) != 1:
        _fail(f"expected one archive member ending in '{suffix}', found {len(matches)}")

    return matches[0]


def _fail(
    message: str,
) -> None:
    raise SystemExit(f"release artifact verification failed: {message}")


if __name__ == "__main__":
    raise SystemExit(main())
