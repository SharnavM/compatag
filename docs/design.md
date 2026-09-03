# Compatag Design

## Purpose

Compatag determines whether published Python package distributions are compatible with a
specified CPython version and deployment platform, and surfaces compatibility and
source-build risks.

## Architectural rule

The compatibility engine is independent of every user-facing transport.

The intended dependency direction is:

```text
                 CLI
                  |
                  v
              Compatag Core
               ^        ^
               |        |
          MCP stdio   MCP HTTP
```

CLI and MCP code may depend on the core.

The core must not depend on CLI, MCP, Claude Code, Codex, or any other client-specific
integration.

## Initial components

The project will grow toward these responsibilities:

- target environment modelling;
- compatibility-tag generation;
- PyPI metadata retrieval;
- requirement and manifest parsing;
- package compatibility analysis;
- target comparison;
- CLI presentation;
- MCP adapters.

Modules will be introduced only when their corresponding functionality is implemented.

## Initial scope

Compatag v0.1 will focus on:

- CPython targets;
- PyPI packages;
- wheel and source-distribution metadata;
- PEP 440 version constraints;
- PEP 508 requirements and environment markers;
- requirements.txt;
- PEP 621 project dependencies in pyproject.toml;
- Windows, manylinux, musllinux, and macOS wheel platforms.

## Explicit non-goals for v0.1

Compatag will not initially:

- resolve transitive dependency graphs;
- build source distributions;
- execute package installation code;
- support private package indexes;
- analyze CUDA or ROCm compatibility;
- parse Conda, Poetry, or Pipenv-specific dependency formats;
- guarantee application runtime compatibility.

## Interface strategy

The compatibility engine will return typed domain results.

CLI and MCP integrations will translate those results for their respective consumers rather than implementing compatibility logic themselves.

Manifest contents will be supplied to remote MCP tools as data rather than granting the server arbitrary filesystem access.

## PyPI data boundary

PyPI access is isolated behind `PyPIClient`.

The client converts external Simple Repository API responses into Compatag
domain models before compatibility analysis begins.

The analyzer must not depend on PyPI's raw JSON field names or HTTP response
objects.

```text
PyPI
  |
  v
PyPIClient
  |
  v
ProjectDistributions
  |
  v
Analyzer
```

External wire models are forward-tolerant. Compatag domain models remain
strict.

This architectural rule will matter in Milestone 3.

The analyzer should never contain code like:

```python
response["files"][0]["requires-python"]
```

It receives a:

```
DistributionFile
```

instead.
