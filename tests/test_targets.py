import pytest
from packaging.tags import Tag
from pydantic import ValidationError

from compatag.targets import TargetEnvironment, compatibility_tags


def test_target_normalizes_user_input() -> None:
    target = TargetEnvironment(
        python_version=" 3.11 ",
        platform=" WIN_AMD64 ",
    )

    assert target.python_version == "3.11"
    assert target.platform == "win_amd64"
    assert target.version_info == (3, 11)


@pytest.mark.parametrize(
    "python_version",
    [
        "3.11.9",
        "3",
        "3.x",
        "3.8",
        "2.7",
    ],
)
def test_target_rejects_unsupported_python_versions(
    python_version: str,
) -> None:
    with pytest.raises(ValidationError):
        TargetEnvironment(
            python_version=python_version,
            platform="win_amd64",
        )


@pytest.mark.parametrize(
    "platform",
    [
        "linux_x86_64",
        "manylinux_2_16_aarch64",
        "manylinux_2_28_notarealarch",
        "musllinux_1_2_notarealarch",
        "macosx_14_4_arm64",
        "freebsd_amd64",
    ],
)
def test_target_rejects_unsupported_platforms(platform: str) -> None:
    with pytest.raises(ValidationError):
        TargetEnvironment(
            python_version="3.11",
            platform=platform,
        )


def test_windows_target_has_expected_cpython_tags() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="win_amd64",
    )

    tags = compatibility_tags(target)

    assert Tag("cp311", "cp311", "win_amd64") in tags
    assert Tag("cp311", "abi3", "win_amd64") in tags
    assert Tag("cp310", "abi3", "win_amd64") in tags
    assert Tag("py3", "none", "any") in tags

    assert Tag("cp311", "cp311", "win_arm64") not in tags


def test_manylinux_target_accepts_older_glibc_baselines() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="manylinux_2_28_x86_64",
    )

    tags = compatibility_tags(target)

    assert Tag("cp311", "cp311", "manylinux_2_28_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux_2_17_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux2014_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux_2_12_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux2010_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux_2_5_x86_64") in tags
    assert Tag("cp311", "cp311", "manylinux1_x86_64") in tags

    assert Tag("cp311", "cp311", "manylinux_2_29_x86_64") not in tags


def test_aarch64_manylinux_target_stops_at_glibc_2_17() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="manylinux_2_17_aarch64",
    )

    tags = compatibility_tags(target)

    assert Tag("cp311", "cp311", "manylinux_2_17_aarch64") in tags
    assert Tag("cp311", "cp311", "manylinux2014_aarch64") in tags

    assert Tag("cp311", "cp311", "manylinux_2_16_aarch64") not in tags


def test_musllinux_target_accepts_older_minor_versions() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="musllinux_1_2_x86_64",
    )

    tags = compatibility_tags(target)

    assert Tag("cp311", "cp311", "musllinux_1_2_x86_64") in tags
    assert Tag("cp311", "cp311", "musllinux_1_1_x86_64") in tags
    assert Tag("cp311", "cp311", "musllinux_1_0_x86_64") in tags

    assert Tag("cp311", "cp311", "musllinux_1_3_x86_64") not in tags


def test_macos_arm_target_accepts_universal2_wheels() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="macosx_14_0_arm64",
    )

    tags = compatibility_tags(target)

    assert Tag("cp311", "cp311", "macosx_14_0_arm64") in tags
    assert Tag("cp311", "cp311", "macosx_14_0_universal2") in tags
    assert Tag("cp311", "cp311", "macosx_13_0_arm64") in tags


def test_exact_target_tag_has_highest_preference() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="manylinux_2_28_x86_64",
    )

    tags = compatibility_tags(target)

    assert tags[0] == Tag(
        "cp311",
        "cp311",
        "manylinux_2_28_x86_64",
    )


def test_compatibility_tags_do_not_contain_duplicates() -> None:
    target = TargetEnvironment(
        python_version="3.11",
        platform="macosx_14_0_arm64",
    )

    tags = compatibility_tags(target)

    assert len(tags) == len(set(tags))
