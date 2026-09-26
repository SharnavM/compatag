# Manifests

Compatag reads direct dependency declarations from requirements-style text and PEP 621 `pyproject.toml` metadata. It supports dependency syntax without reproducing the full behavior of pip or a build backend.

The CLI reads UTF-8 files, with an optional UTF-8 BOM. MCP tools receive the manifest text from the client. Commands and tool inputs are covered in [Usage](USAGE.md).

## Requirements-style files

Each dependency uses standard Python requirement syntax:

```text
requests>=2
numpy>=2,<3
httpx[http2]>=0.28
colorama ; sys_platform == "win32"
```

Blank lines, full-line comments, and whitespace-delimited inline comments are supported. An unescaped trailing backslash joins physical lines:

```text
numpy>=2,\
    <3
```

Markers are preserved and evaluated for the target during analysis. Their supported variables and unresolved cases are described in [Compatibility](COMPATIBILITY.md#python-requirements-and-markers).

Requirement extras such as `httpx[http2]` are parsed, but the dependencies introduced by the extra are not resolved. The check covers the published `httpx` distribution and includes a note about this limitation.

### Unsupported installer syntax

The following produce parsing issues rather than being followed or silently ignored:

- Includes and constraints: `-r`, `--requirement`, `-c`, and `--constraint`.
- Editable installations and local paths, including `-e`.
- Index and file-search options such as `--index-url`, `--extra-index-url`, and `--find-links`.
- Installer options such as `--only-binary`, `--prefer-binary`, and per-requirement hashes.
- Unnamed URLs and version-control URLs.

A named direct reference such as `example @ https://example.com/example.whl` can be parsed, but analysis returns `UNKNOWN` with status `unsupported_requirement`. Compatag does not fetch that URL. Arbitrary equality requirements using `===` are also unsupported by the analyzer.

## PEP 621 projects

Compatag reads base dependencies and the project's Python requirement from `[project]`:

```toml
[project]
name = "example-app"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.28",
    "colorama; sys_platform == 'win32'",
]

[project.optional-dependencies]
dev = ["pytest"]
docs = ["sphinx"]
all = ["example-app[dev,docs]"]
```

Base dependencies are included by default. Optional groups are added only when selected through CLI `--extra` options or the MCP `extras` argument. Multiple groups can be selected, and names are normalized before matching. An unknown requested group makes the manifest incomplete.

Simple references to the project's own extras support group composition: selecting `all` above includes `dev` and `docs`. Self-references with version constraints, markers, or direct URLs are not supported.

Selecting a project's optional group adds its declared requirements. This differs from resolving dependencies behind a published package extra such as `httpx[http2]`, which is outside the current scope.

Compatag does not read dependency declarations from `[build-system]`, `[dependency-groups]`, or tool-specific tables such as `[tool.poetry]`. It does not parse lockfiles or execute build backends.

## Dynamic metadata

Dynamic fields cannot be fully established from static source text:

| Declaration | Behavior |
| --- | --- |
| Dynamic `dependencies` | Retains any static dependency entries and marks the manifest incomplete. |
| Dynamic `optional-dependencies` | Marks selected optional groups incomplete; the dynamic declaration alone does not block a base-only audit. |
| Dynamic `requires-python` | Reports project Python compatibility as unavailable and marks the manifest incomplete. |
| Missing `[project]` table | Reports unavailable project metadata, rather than treating valid TOML as a syntax error. |

Malformed TOML, invalid dependency entries, and invalid project metadata are reported as parsing issues.

## Incomplete manifests and audit results

Valid requirements remain available for analysis when other entries cannot be interpreted. For example:

```text
requests>=2
-r private.txt
```

Compatag checks `requests`, reports the unsupported include, and sets `manifest_complete` to `false`. It does not read `private.txt`.

An error makes the manifest incomplete. A warning, such as a duplicate requirement, does not. Equivalent checks are reused, while source occurrences and their counts remain visible.

With no confirmed compatibility failure, parsing errors make the audit `UNKNOWN`. A confirmed package or project Python failure takes precedence and makes it `FAIL`. Non-blocking parsing warnings make an otherwise clean audit `WARN`.

Requirements-style issues identify line locations; pyproject issues identify fields such as `project.dependencies[0]`. These locations help readers find the original declaration.
