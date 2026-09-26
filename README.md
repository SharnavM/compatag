<h1 align="center">Compatag</h1>

<p align="center">
  <a href="https://github.com/SharnavM/compatag/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/SharnavM/compatag/test.yml?label=CI" alt="CI status"></a> <a href="https://pypi.org/project/compatag/"><img src="https://img.shields.io/pypi/v/compatag" alt="PyPI version"></a> <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-%3E%3D3.11-blue" alt="Python >=3.11"></a> <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT license"></a>
</p>

Compatag preflights Python package compatibility before deployment. It checks published PyPI package artifacts against explicit Python versions and platforms, identifying compatible wheels and cases that may require a source build.

Compatag is available through a command-line interface and a local MCP server. Its results describe published metadata and artifacts; they do not guarantee that an application will run successfully.

## Contents

- [Demo](#demo)
- [Features](#features)
- [Installation](#installation)
- [How to Use](#how-to-use)
- [Current Scope and Limitations](#current-scope-and-limitations)
- [To-do](#to-do)
- [License](#license)

## Demo

The video shows Compatag's MCP server in action with Codex. Playback is deliberately slowed during tool calls and while Codex presents conclusions based on the results, making these steps easier to follow.

https://github.com/user-attachments/assets/709741e3-4c93-4ec7-8706-19bcb4995c2e

## Features

- **Package checks**: Checks a single Python requirement against an explicit CPython version and platform.
- **Dependency audits**: Audits direct dependencies in requirements-style files and PEP 621 `pyproject.toml` files, including selected optional dependency groups.
- **Wheel and source-build detection**: Detects compatible wheels and source-build requirements, taking `Requires-Python` and environment markers into account.
- **Target comparisons**: Compares two deployment targets, reporting compatibility, selected-version, artifact, and dependency-applicability changes.
- **CLI and MCP support**: Provides CLI commands with JSON output and three tools through a local MCP stdio server.
- **Concurrent analysis**: Analyzes PyPI packages concurrently, with configurable concurrency and resource limits.

## Installation

Compatag requires Python 3.11 or newer. CI covers Python 3.11-3.14 on Windows and Ubuntu.

### From PyPI

```bash
pip install compatag
```

### From source

```bash
git clone https://github.com/SharnavM/compatag.git
cd compatag
python -m pip install .
```

For development, an editable installation includes the test and code-checking tools:

```bash
python -m pip install -e ".[dev]"
```

## How to Use

### CLI

Each command takes an explicit deployment target, independent of the machine running Compatag.

A single requirement check:

```bash
compatag check "numpy>=2,<3" --python 3.11 --platform manylinux_2_17_aarch64
```

A direct-dependency audit:

```bash
compatag audit requirements.txt --python 3.11 --platform win_amd64
```

For a project with a `dev` optional dependency group:

```bash
compatag audit pyproject.toml --extra dev --python 3.11 --platform win_amd64
```

A comparison between Windows x64 and ARM64 Linux:

```bash
compatag compare requirements.txt --from-python 3.11 --from-platform win_amd64 --to-python 3.11 --to-platform manylinux_2_17_aarch64
```

All three analysis commands support `--json` for structured output. The [CLI guide](docs/USAGE.md#cli) covers complete options, exit codes, and further examples.

### MCP

Compatag exposes a local MCP stdio server through `compatag-mcp`. The MCP client launches the server and receives these tools:

| Tool              | Purpose                                                   |
| ----------------- | --------------------------------------------------------- |
| `check_package`   | Checks one requirement against a target.                  |
| `audit_manifest`  | Audits a manifest's direct dependencies against a target. |
| `compare_targets` | Compares a manifest across two targets.                   |

The following registration examples assume that Compatag is installed and `compatag-mcp` is available on the client's `PATH`.

**[Codex CLI](https://developers.openai.com/codex/mcp):**

```bash
codex mcp add compatag -- compatag-mcp
```

**[Claude Code](https://code.claude.com/docs/en/mcp):**

```bash
claude mcp add --transport stdio compatag -- compatag-mcp
```

**Other clients (Cursor, Antigravity, and similar editors):**

Local stdio configuration uses `compatag-mcp` as the command, with no arguments. For clients that accept an `mcpServers` configuration, such as [Cursor](https://docs.cursor.com/context/model-context-protocol), a minimal entry is:

```json
{
  "mcpServers": {
    "compatag": {
      "command": "compatag-mcp",
      "args": []
    }
  }
}
```

The configuration location and format depend on the client. An absolute executable path can replace `compatag-mcp` when the installation is outside the client's `PATH`.

MCP manifest tools receive manifest contents, not arbitrary filesystem paths. The client reads the file and passes its text to Compatag. The [MCP guide](docs/USAGE.md#mcp) covers tool inputs, optional groups, and result handling.

## Current Scope and Limitations

- Analysis covers direct dependencies. Transitive dependencies are not resolved.
- Interpreter support is currently limited to CPython.
- Results are based on published PyPI distribution metadata and artifacts. Compatag does not execute packages or guarantee application or runtime compatibility.
- A source distribution means a source build may be required. Compatag does not build it or prove that the build will succeed.
- Markers and Python constraints that cannot be resolved from the supplied target are reported as indeterminate.
- Direct URL requirements and local package paths are outside the current analysis scope. Pip directives such as `-r`, `-c`, `-e`, and `--index-url` produce manifest issues. Dynamically supplied project dependencies cannot be fully audited from static text.

The [manifest guide](docs/MANIFESTS.md) describes supported input syntax and limitations.

Further documentation covers [compatibility results](docs/COMPATIBILITY.md), [architecture](docs/ARCHITECTURE.md), [development](docs/DEVELOPMENT.md), and [releasing](docs/RELEASING.md).

## To-do

- [ ] Transitive dependency resolution.
- [ ] Streamable HTTP MCP transport for remote deployment.

## License

Compatag is released under the [MIT License](LICENSE).
