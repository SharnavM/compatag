# Manifest Parsing

## Purpose

Compatag parses dependency manifests into structured direct requirements
before compatibility analysis begins.

Manifest parsing does not access PyPI and does not make deployment compatibility decisions.

## Supported formats

The initial parser supports:

```text
requirements.txt-style input
PEP 621 pyproject.toml
```

The parsers operate on manifest text rather than filesystem paths.

## Result model

Parsing produces a `ParsedManifest` containing:

```text
format
project_name
requires_python
selected_extras
requirements
issues
```

Each requirement retains its original dependency specifier and source location.

## Completeness

Parsing is intentionally recoverable.

Unsupported or malformed entries do not necessarily discard valid requirements from the rest of the manifest.

Issues have two severity levels:

```text
WARNING
ERROR
```

An error means Compatag cannot claim that the parsed dependency set is complete.

`ParsedManifest.is_complete` is false whenever at least one error is present.

Warnings do not make the manifest incomplete.

## requirements.txt

Compatag supports the portable requirement-specifier subset of pip requirements files.

Supported examples include:

```text
requests
requests>=2
numpy>=2,<3
httpx[http2]>=0.28
colorama ; sys_platform == "win32"
```

Full-line and whitespace-delimited inline comments are supported.

Unescaped trailing backslashes create logical line continuations.

Example:

```text
numpy>=2,\
    <3
```

is represented as one requirement while retaining the physical source line range.

### Unsupported pip-specific syntax

The initial parser does not interpret pip command-line directives such as:

```text
-r
-c
-e
--index-url
--extra-index-url
--find-links
--only-binary
--prefer-binary
```

These entries produce blocking parse issues rather than being silently ignored.

Unnamed URLs and filesystem paths are also outside the initial PyPI-only scope.

Named PEP 508 direct references may be parsed as requirements, but the package analyzer currently reports direct URLs as unsupported.

## pyproject.toml

Compatag reads standardized `[project]` metadata using Python's built-in
`tomllib` module.

Base dependencies are read from:

```toml
[project]
dependencies = [
    "httpx",
    "pydantic",
]
```

The project's Python requirement is read from:

```toml
[project]
requires-python = ">=3.11"
```

## Optional dependencies

Optional groups are selected explicitly.

For example:

```toml
[project.optional-dependencies]
postgres = ["psycopg"]
docs = ["sphinx"]
```

A base-only parse includes neither group.

Requesting the `postgres` extra adds `psycopg` to the parsed dependency set.

Extra names are normalized before comparison.

## Self-referential extras

Compatag supports simple optional-group composition.

Example:

```toml
[project]
name = "demo"

[project.optional-dependencies]
cli = ["click"]
docs = ["sphinx"]
all = ["demo[cli,docs]"]
```

Selecting `all` expands the `cli` and `docs` groups rather than treating `demo[cli,docs]` as an external package dependency.

Self-references containing version constraints, markers, or direct URLs are outside the initial scope and produce a blocking issue.

## Dynamic metadata

Modern pyproject metadata may declare list or table fields both statically and dynamically.

Example:

```toml
[project]
dependencies = [
    "torch",
    "packaging",
]
dynamic = ["dependencies"]
```

Compatag retains the statically declared entries but reports the dependency set as incomplete because the build backend may append additional entries.

Dynamic optional dependencies only block completeness when optional groups are requested.

A dynamic `requires-python` value is treated as unresolved because Compatag cannot determine its final value from static source text.

## Missing project table

A pyproject.toml without `[project]` does not necessarily represent malformed TOML.

The build backend may provide standardized project metadata dynamically.

Compatag therefore reports dynamic project metadata rather than an invalid
TOML error.

## Source locations

Requirements-file entries retain physical line ranges.

Example:

```text
line_start = 12
line_end = 13
```

pyproject dependencies use structural source identifiers such as:

```text
project.dependencies[2]
project.optional-dependencies.dev[1]
```

Compatag does not fabricate TOML line numbers when the parser cannot provide reliable source spans.

## Architectural boundary

Manifest parsing produces data for later analysis:

```text
manifest text
      |
      v
manifest parser
      |
      v
ParsedManifest
      |
      v
manifest auditor
      |
      v
package analyzer
```

Manifest parsers do not access PyPI.

Package analysis does not parse manifest file syntax.
