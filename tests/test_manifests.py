import pytest

from compatag.manifests import (
    ManifestFormat,
    ManifestIssueCode,
    ManifestIssueSeverity,
    ParsedManifest,
    parse_pyproject,
    parse_requirements,
)


def _issue_codes(result: ParsedManifest) -> set[ManifestIssueCode]:
    return {issue.code for issue in result.issues}


def test_requirements_parses_basic_dependencies() -> None:
    text = '# Runtime dependencies\nrequests>=2\n\ncolorama>=0.4; sys_platform == "win32"\n'

    result = parse_requirements(text)

    assert result.format is ManifestFormat.REQUIREMENTS
    assert result.is_complete

    assert [requirement.name for requirement in result.requirements] == [
        "requests",
        "colorama",
    ]

    assert result.requirements[0].line_start == 2
    assert result.requirements[0].line_end == 2


def test_requirements_strips_inline_comment() -> None:
    result = parse_requirements("requests>=2  # HTTP client\n")

    assert len(result.requirements) == 1
    assert result.requirements[0].text == "requests>=2"


def test_comment_marker_inside_quotes_is_preserved() -> None:
    result = parse_requirements('demo; platform_release == "build #42"\n')

    assert len(result.requirements) == 1

    assert result.requirements[0].text == ('demo; platform_release == "build #42"')


def test_named_url_fragment_is_not_treated_as_comment() -> None:
    result = parse_requirements(
        "demo @ https://example.test/demo.whl#sha256=abc # pinned artifact\n"
    )

    assert len(result.requirements) == 1

    assert result.requirements[0].text == ("demo @ https://example.test/demo.whl#sha256=abc")


def test_line_continuation_preserves_source_range() -> None:
    text = "numpy>=2,\\\n    <3\n"

    result = parse_requirements(text)

    assert result.is_complete
    assert len(result.requirements) == 1

    requirement = result.requirements[0]

    assert requirement.text == ("numpy>=2,    <3")

    assert requirement.line_start == 1
    assert requirement.line_end == 2


def test_unterminated_continuation_is_blocking() -> None:
    result = parse_requirements("numpy>=2,\\")

    assert not result.is_complete

    assert ManifestIssueCode.UNTERMINATED_CONTINUATION in _issue_codes(result)


@pytest.mark.parametrize(
    "entry",
    [
        "-r base.txt",
        "--requirement base.txt",
        "-c constraints.txt",
        "--index-url https://example.test/simple",
        "-e .",
        "--only-binary :all:",
    ],
)
def test_pip_directives_are_reported(
    entry: str,
) -> None:
    result = parse_requirements(f"{entry}\n")

    assert result.requirements == ()
    assert not result.is_complete

    assert ManifestIssueCode.UNSUPPORTED_DIRECTIVE in _issue_codes(result)


@pytest.mark.parametrize(
    "entry",
    [
        "https://example.test/demo.whl",
        "./local-package",
        "../local-package",
        r"C:\packages\demo.whl",
    ],
)
def test_unnamed_external_entries_are_reported(
    entry: str,
) -> None:
    result = parse_requirements(f"{entry}\n")

    assert result.requirements == ()

    assert ManifestIssueCode.UNSUPPORTED_ENTRY in _issue_codes(result)


def test_invalid_requirement_is_reported() -> None:
    result = parse_requirements("not a valid requirement !!!\n")

    assert result.requirements == ()

    assert ManifestIssueCode.INVALID_REQUIREMENT in _issue_codes(result)

    assert not result.is_complete


def test_duplicate_requirement_is_warning_only() -> None:
    result = parse_requirements("requests>=2\nrequests>=2\n")

    assert len(result.requirements) == 2
    assert result.is_complete

    issue = result.issues[0]

    assert issue.code is ManifestIssueCode.DUPLICATE_REQUIREMENT

    assert issue.severity is ManifestIssueSeverity.WARNING


def test_pyproject_parses_base_dependencies() -> None:
    text = """
[project]
name = "Demo_Project"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.28",
    "pydantic>=2",
]
"""

    result = parse_pyproject(text)

    assert result.format is ManifestFormat.PYPROJECT
    assert result.project_name == "demo-project"
    assert result.requires_python == ">=3.11"
    assert result.selected_extras == ()
    assert result.is_complete

    assert [requirement.name for requirement in result.requirements] == [
        "httpx",
        "pydantic",
    ]

    assert result.requirements[0].source == ("project.dependencies[0]")

    assert result.requirements[0].line_start is None


def test_optional_dependencies_are_not_included_by_default() -> None:
    text = """
[project]
name = "demo"
dependencies = ["httpx"]

[project.optional-dependencies]
dev = ["pytest"]
docs = ["sphinx"]
"""

    result = parse_pyproject(text)

    assert [requirement.name for requirement in result.requirements] == ["httpx"]


def test_requested_optional_group_is_included() -> None:
    text = """
[project]
name = "demo"
dependencies = ["httpx"]

[project.optional-dependencies]
dev = [
    "pytest",
    "ruff",
]
"""

    result = parse_pyproject(
        text,
        extras=["dev"],
    )

    assert result.selected_extras == ("dev",)

    assert [requirement.name for requirement in result.requirements] == [
        "httpx",
        "pytest",
        "ruff",
    ]


def test_requested_extra_name_is_normalized() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
dev-test = ["pytest"]
"""

    result = parse_pyproject(
        text,
        extras=["DEV_TEST"],
    )

    assert result.selected_extras == ("dev-test",)

    assert [requirement.name for requirement in result.requirements] == ["pytest"]


def test_self_referential_extra_composes_groups() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
all = ["demo[cli,docs]"]
cli = ["click"]
docs = ["sphinx"]
"""

    result = parse_pyproject(
        text,
        extras=["all"],
    )

    assert result.is_complete

    assert {requirement.name for requirement in result.requirements} == {
        "click",
        "sphinx",
    }


def test_complex_self_reference_is_reported() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
all = ["demo[docs]>=1"]
docs = ["sphinx"]
"""

    result = parse_pyproject(
        text,
        extras=["all"],
    )

    assert not result.is_complete

    assert ManifestIssueCode.UNSUPPORTED_SELF_REFERENCE in _issue_codes(result)


def test_unknown_optional_group_is_blocking() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
dev = ["pytest"]
"""

    result = parse_pyproject(
        text,
        extras=["docs"],
    )

    assert not result.is_complete

    assert ManifestIssueCode.UNKNOWN_OPTIONAL_GROUP in _issue_codes(result)


def test_static_dynamic_dependencies_are_parsed_but_incomplete() -> None:
    text = """
[project]
name = "demo"
dependencies = ["torch", "packaging"]
dynamic = ["dependencies"]
"""

    result = parse_pyproject(text)

    assert {requirement.name for requirement in result.requirements} == {
        "torch",
        "packaging",
    }

    assert not result.is_complete

    assert ManifestIssueCode.DYNAMIC_DEPENDENCIES in _issue_codes(result)


def test_dynamic_optional_dependencies_are_incomplete_when_selected() -> None:
    text = """
[project]
name = "demo"
dynamic = ["optional-dependencies"]

[project.optional-dependencies]
dev = ["pytest"]
"""

    result = parse_pyproject(
        text,
        extras=["dev"],
    )

    assert [requirement.name for requirement in result.requirements] == ["pytest"]

    assert not result.is_complete

    assert ManifestIssueCode.DYNAMIC_OPTIONAL_DEPENDENCIES in _issue_codes(result)


def test_dynamic_optional_dependencies_do_not_block_base_only_parse() -> None:
    text = """
[project]
name = "demo"
dependencies = ["httpx"]
dynamic = ["optional-dependencies"]
"""

    result = parse_pyproject(text)

    assert result.is_complete

    assert [requirement.name for requirement in result.requirements] == ["httpx"]


def test_dynamic_requires_python_is_blocking() -> None:
    text = """
[project]
name = "demo"
dynamic = ["requires-python"]
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.DYNAMIC_REQUIRES_PYTHON in _issue_codes(result)


def test_missing_project_table_is_dynamic_metadata() -> None:
    text = """
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.DYNAMIC_PROJECT_METADATA in _issue_codes(result)


def test_invalid_toml_is_reported() -> None:
    result = parse_pyproject("[project\nname = 'demo'")

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_TOML in _issue_codes(result)


def test_invalid_requires_python_is_reported() -> None:
    text = """
[project]
name = "demo"
requires-python = "definitely-not-valid"
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_REQUIRES_PYTHON in _issue_codes(result)


def test_non_string_dependency_is_reported() -> None:
    text = """
[project]
name = "demo"
dependencies = [
    "httpx",
    42,
]
"""

    result = parse_pyproject(text)

    assert [requirement.name for requirement in result.requirements] == ["httpx"]

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_DEPENDENCIES in _issue_codes(result)


def test_invalid_optional_group_value_is_reported_when_selected() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
dev = "pytest"
"""

    result = parse_pyproject(
        text,
        extras=["dev"],
    )

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_OPTIONAL_DEPENDENCIES in _issue_codes(result)


def test_normalized_optional_group_collision_is_reported() -> None:
    text = """
[project]
name = "demo"

[project.optional-dependencies]
dev_test = ["pytest"]
dev-test = ["ruff"]
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.AMBIGUOUS_OPTIONAL_GROUP in _issue_codes(result)


def test_invalid_project_name_is_reported() -> None:
    text = """
[project]
name = "not a valid project name!"
dependencies = ["httpx"]
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_PROJECT_NAME in _issue_codes(result)


def test_invalid_dynamic_value_is_reported() -> None:
    text = """
[project]
name = "demo"
dynamic = "dependencies"
dependencies = ["httpx"]
"""

    result = parse_pyproject(text)

    assert not result.is_complete

    assert ManifestIssueCode.INVALID_DYNAMIC in _issue_codes(result)
