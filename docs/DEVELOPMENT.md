# Development

Compatag requires Python 3.11 or newer. CI tests Python 3.11–3.14 on Windows and Ubuntu. Python 3.11 is used for quality and release checks.

## Environment setup

After cloning the repository, development uses a virtual environment and the `dev` extra.

Windows CMD:

```cmd
git clone https://github.com/SharnavM/compatag.git
cd compatag
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Linux:

```bash
git clone https://github.com/SharnavM/compatag.git
cd compatag
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Local checks

The following commands run from the repository root in the activated environment:

```cmd
python -m pip check
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

Coverage reporting:

```cmd
python -m pytest --cov=compatag --cov-report=term-missing
```

A focused test run can select a file:

```cmd
python -m pytest tests/test_cli.py
```

Tests use controlled repository responses rather than live PyPI lookups. MCP coverage includes a subprocess test that starts the stdio server and discovers its tools. Dependency installation still requires access to the configured package index.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`src/compatag/`](../src/compatag/) | Library and interface code. |
| [`tests/`](../tests/) | Package analysis, manifests, targets, adapters, and repository-client tests. |
| [`pyproject.toml`](../pyproject.toml) | Package metadata, dependencies, entry points, and tool settings. |
| [`scripts/verify_release_artifacts.py`](../scripts/verify_release_artifacts.py) | Wheel and source-distribution checks. |
| [`.github/workflows/`](../.github/workflows/) | CI and publishing workflows. |

[Architecture](ARCHITECTURE.md) explains module responsibilities. [Usage](USAGE.md) documents public commands and tools.

## CI and builds

The [CI workflow](../.github/workflows/test.yml) runs on pushes and pull requests. Its Windows and Ubuntu matrix checks installed dependencies, tests, and the module entry point across Python 3.11–3.14. Separate jobs run Ruff, formatting checks, mypy, coverage, package builds, and distribution metadata checks.

A local build uses:

```cmd
python -m build
python scripts/verify_release_artifacts.py
python -m twine check --strict dist/*
```

The artifact verifier expects exactly one wheel and one `.tar.gz` source distribution in `dist/`, matching the current project version. Old build artifacts must be moved out before verification. [Releasing](RELEASING.md) covers release preparation, publishing, and installation checks.
