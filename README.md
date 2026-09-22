# Compatag

**Preflight Python package compatibility across Python versions and deployment platforms.**

Compatag is an open-source Python developer tool for determining whether published Python
package distributions are compatible with a target CPython version and platform.

The project is currently in early development.

## Planned interfaces

Compatag will expose the same compatibility engine through:

- a command-line interface;
- a local MCP server over stdio;
- an optional remote MCP server over Streamable HTTP.

The MCP interface is intended to work with standards-compliant MCP clients, including Claude Code and Codex CLI.

## CLI

Check one package:

```cmd
compatag check "numpy>=2,<3" --python 3.11 --platform manylinux_2_17_aarch64
```

Audit a project:

```cmd
compatag audit requirements.txt --python 3.11 --platform manylinux_2_17_aarch64
```

Compare deployment targets:

```cmd
compatag compare requirements.txt --from-python 3.11 --from-platform win_amd64 --to-python 3.11 --to-platform manylinux_2_17_aarch64
```

Add `--json` to any analysis command for structured output.

## Scope

Compatag will inspect package metadata, Python version requirements, distribution artifacts,
and wheel compatibility tags.

It will not execute third-party package code or claim that an application is guaranteed to
run successfully on a target system.

## Development

Compatag requires Python 3.11 or newer.

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest
```

Run static checks:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

## Status

Pre-alpha.

Implemented:

- deployment target modelling;
- cross-platform wheel compatibility-tag generation;
- asynchronous PyPI Simple API retrieval;
- published distribution classification and metadata normalization;
- single-package compatibility analysis;
- requirements.txt and PEP 621 pyproject.toml parsing;
- project-wide compatibility auditing;
- target-to-target compatibility comparison;
- bounded asynchronous PyPI analysis;
- CLI package checks;
- CLI manifest audits;
- CLI target comparisons;
- structured JSON CLI output;
- CI-friendly exit-code semantics.

MCP interfaces, public packaging, and remote deployment are still under
development.

## License

MIT
