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

Target environment modelling and cross-platform wheel tag generation are implemented. Package metadata analysis, manifest auditing, and MCP interfaces are still under development.

## License

MIT
