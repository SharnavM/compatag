# Releasing

Releases are built and published by the [release workflow](../.github/workflows/release.yml) when a GitHub Release is published. A tag push alone does not trigger publishing.

## Versions and tags

The package version is defined in `[project].version` in [`pyproject.toml`](../pyproject.toml). Versions use Python packaging's PEP 440 format, for example `0.1.0` or `0.1.0rc1`. The release tag must be `v` followed by the normalized version, such as `v0.1.0`.

The workflow rejects development versions such as `0.1.0.dev0` and mismatched tags. For the first stable release, the version must be changed to `0.1.0` and committed before the `v0.1.0` tag is created.

## Publishing setup

The repository uses PyPI Trusted Publishing through GitHub Actions. The publisher configuration must match:

| Setting | Value |
| --- | --- |
| PyPI project | `compatag` |
| Repository owner | `SharnavM` |
| Repository | `compatag` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

The repository must have a GitHub environment named `pypi`, with any desired reviewer or tag restrictions configured before release. The publish job requests `id-token: write` and uses the PyPI publishing action.

For an existing project, the maintainer configures the publisher in the project's PyPI Publishing settings. [PyPI's Trusted Publisher guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) describes the fields.

For a new project, a pending publisher is configured in the PyPI account's Publishing settings. The first successful publication creates the project and converts the pending publisher into a regular publisher. A pending publisher does not reserve the project name. [PyPI's first-project guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) covers this setup.

## Local preflight

The release commit should have passing CI and the intended version, README, license, and dependency metadata. In an activated development environment, the local checks are:

```cmd
python -m pip install -e ".[dev]"
python -m pip check
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

Before building, `dist/` should be absent or empty of earlier release artifacts. The build and verification commands are:

```cmd
python -m build
python scripts/verify_release_artifacts.py
python -m twine check --strict dist/*
```

The verifier checks that exactly one wheel and one source distribution exist, that names and versions match project metadata, and that required package files and CLI entry points are present. It also checks wheel metadata, runtime dependencies, and the expected `py3-none-any` tag. Twine validates distribution metadata and README rendering.

Installation checks use separate clean environments for the wheel and source distribution. For `0.1.0`, Windows CMD commands are:

```cmd
py -3.11 -m venv .venv-wheel-check
.venv-wheel-check\Scripts\python -m pip install dist/compatag-0.1.0-py3-none-any.whl
.venv-wheel-check\Scripts\python -m pip check
.venv-wheel-check\Scripts\compatag --version
.venv-wheel-check\Scripts\python -c "from compatag.mcp_server import mcp; print(mcp.name)"

py -3.11 -m venv .venv-sdist-check
.venv-sdist-check\Scripts\python -m pip install dist/compatag-0.1.0.tar.gz
.venv-sdist-check\Scripts\python -m pip check
.venv-sdist-check\Scripts\compatag --version
.venv-sdist-check\Scripts\python -c "from compatag.mcp_server import mcp; print(mcp.name)"
```

For another release, filenames use that release's version. On Linux, environment creation uses `python3.11 -m venv`, and executables are under `bin/` instead of `Scripts/`. The release workflow performs clean wheel and source-distribution installations and checks that the MCP launcher exists.

## First-release sequence

1. The maintainer configures the `pypi` GitHub environment and the matching PyPI pending publisher, or an existing project's publisher.
2. The release commit sets version `0.1.0`, passes local preflight, and passes CI.
3. The maintainer creates tag `v0.1.0` on that commit and publishes a GitHub Release for the tag with concise release notes.
4. The workflow verifies the source, checks tag/version agreement, builds and validates both distributions, and tests clean installations.
5. The publish job uses the `pypi` environment. Any configured environment review must complete before publishing.
6. After publication, the maintainer verifies the PyPI version, files, rendered description, and installation.

Later releases follow the same process with a new version and tag.

## Post-release verification

A fresh environment verifies installation from PyPI. For the first release on Windows CMD:

```cmd
py -3.11 -m venv .venv-pypi-check
.venv-pypi-check\Scripts\python -m pip install --index-url https://pypi.org/simple "compatag==0.1.0"
.venv-pypi-check\Scripts\python -m pip check
.venv-pypi-check\Scripts\compatag --version
.venv-pypi-check\Scripts\compatag --help
.venv-pypi-check\Scripts\python -c "from compatag.mcp_server import mcp; print(mcp.name)"
```

An MCP client can then use the installed `compatag-mcp` launcher and confirm discovery of `check_package`, `audit_manifest`, and `compare_targets`, following [Usage](USAGE.md#mcp).

## Broken releases

If publishing fails, the maintainer checks the failed job and PyPI before retrying, including whether either artifact was uploaded. An unchanged release can be retried after an external setup failure only when no files were published. The workflow does not skip existing uploads.

A code or packaging correction receives a new version and tag. Published versions are not replaced, and a released tag is not moved to different code.

For a published release that should no longer be selected normally, the maintainer can yank it on PyPI with a clear reason and publish a corrected version. Yanking preserves the release, and exact version pins may still install it; it does not remove existing installations. [PyPI's yanking guide](https://docs.pypi.org/project-management/yanking/) describes the process.
