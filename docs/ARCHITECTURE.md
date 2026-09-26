# Architecture

Compatag's core library evaluates published Python package artifacts for explicit deployment targets. Both the CLI and local MCP stdio server use the same parsing, analysis, auditing, and comparison logic.

## Data flow

```text
CLI arguments and files          MCP tool arguments and manifest text
           |                                  |
           +----------------+-----------------+
                            |
                   Target validation
                            |
             Single requirement or manifest parsing
                            |
               Package check / audit / comparison
                            |
                    Package analysis <--- PyPI metadata
                            |
                     Structured results
                            |
                  CLI text/JSON or MCP output
```

## Core responsibilities

All module paths below are relative to [`src/compatag/`](../src/compatag/).

| Area | Modules | Responsibility |
| --- | --- | --- |
| Targets | `targets.py` | Validates CPython versions and platforms and generates accepted wheel tags independently of the host machine. |
| Repository data | `pypi.py`, `distributions.py` | Retrieves PyPI Simple API JSON and represents published versions, files, Python requirements, and yank information. |
| Package analysis | `analyzer.py`, `python_compat.py` | Evaluates requirements, markers, release versions, wheel tags, and Python constraints; returns a result with supporting notes. |
| Manifest parsing | `manifests.py` | Reads requirements-style text and PEP 621 metadata, selects optional groups, and records parsing issues and source locations. |
| Manifest auditing | `audit.py` | Checks project Python requirements, schedules direct package checks with bounded concurrency, and combines results. |
| Target comparison | `compare.py` | Audits the same manifest for two targets and reports compatibility and artifact changes. |
| Resource limits | `limits.py` | Defines analysis and input limits used by the core and adapters. |

Parsing does not contact PyPI. Package analysis consumes normalized repository data rather than handling HTTP responses. The PyPI client retrieves metadata without downloading or executing package distributions.

Audits reuse equivalent checks while retaining each requirement's source occurrence. Comparisons share repository metadata between the two audits and evaluate compatibility separately for each target. Findings remain in manifest order regardless of request completion order.

## Interfaces

The CLI adapter, `cli.py`, handles arguments, reads manifest files, selects text or JSON output, and returns process exit codes. `__main__.py` supports `python -m compatag`.

The MCP adapter, `mcp_server.py`, registers three tools and starts the local stdio server. It receives manifest text from the client and returns structured core results. A PyPI client is shared for the server's lifetime.

The adapters handle presentation and transport; compatibility rules remain in the core library.

## Further reading

- [Usage](USAGE.md): CLI commands and MCP inputs.
- [Compatibility](COMPATIBILITY.md): target support and result meanings.
- [Manifests](MANIFESTS.md): supported dependency syntax.
- [Development](DEVELOPMENT.md): contributor setup and checks.
