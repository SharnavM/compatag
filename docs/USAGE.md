# Usage

Compatag provides a CLI and a local MCP stdio server. Both use the same analysis rules. [Installation instructions](../README.md#installation), [supported manifests](MANIFESTS.md), and [compatibility results](COMPATIBILITY.md) provide the supporting details.

## CLI

### Package checks

`check` evaluates one requirement for an explicit target:

```cmd
compatag check "numpy>=2,<3" --python 3.11 --platform manylinux_2_17_aarch64
```

Quotes protect requirement operators from shell interpretation. `--python` uses a major/minor CPython version; `--platform` uses a wheel platform tag.

### Manifest audits

`audit` checks a manifest's direct dependencies and, for pyproject input, its project Python requirement:

```cmd
compatag audit requirements.txt --python 3.11 --platform win_amd64
compatag audit pyproject.toml --python 3.11 --platform manylinux_2_17_aarch64
```

Optional groups are selected with repeatable `--extra` options. The following assumes that the project declares `dev` and `docs` groups:

```cmd
compatag audit pyproject.toml --extra dev --extra docs --python 3.11 --platform win_amd64
```

### Target comparisons

`compare` evaluates the same manifest for a source and destination target:

```cmd
compatag compare requirements.txt --from-python 3.11 --from-platform win_amd64 --to-python 3.11 --to-platform manylinux_2_17_aarch64
```

Windows CMD supports `^` for a multiline form:

```cmd
compatag compare pyproject.toml --extra dev ^
  --from-python 3.11 --from-platform win_amd64 ^
  --to-python 3.11 --to-platform manylinux_2_17_aarch64
```

The one-line form also works in PowerShell and POSIX shells.

### Options

| Option | Commands | Behavior |
| --- | --- | --- |
| `--json` | `check`, `audit`, `compare` | Returns structured JSON for analysis results. |
| `--strict` | `check`, `audit` | Returns exit code 1 for warnings as well as failures. |
| `--type requirements` or `--type pyproject` | `audit`, `compare` | Overrides manifest format detection. |
| `--extra NAME` | `audit`, `compare` | Adds a pyproject optional dependency group; repeatable. Invalid for requirements-style input. |
| `--verbosity problems` or `--verbosity all` | `audit` | Defaults to `problems`, which includes warnings, failures, unknowns, and passing findings with notes. |
| `--verbosity changes` or `--verbosity all` | `compare` | Defaults to `changes`, which includes changed and indeterminate comparisons. |
| `--concurrency N` | `audit`, `compare` | Limits simultaneous package checks; default 8, accepted range 1–32. |

`all` includes every requirement occurrence. Verbosity filters detailed findings in both text and JSON; aggregate counts always include all occurrences. `--json` does not change exit codes, and argument or file errors can still be printed to standard error as text.

Examples:

```cmd
compatag check "numpy>=2,<3" --python 3.11 --platform win_amd64 --json --strict
compatag audit requirements.txt --python 3.11 --platform win_amd64 --verbosity all --concurrency 4
compatag audit dependencies.list --type requirements --python 3.11 --platform win_amd64
```

Manifest detection recognizes `pyproject.toml`, `requirements.txt`, `requirements.in`, and filenames beginning with `requirements-` or `requirements_`, ignoring case. Other names require `--type`.

Built-in help and version information are available through:

```cmd
compatag --help
compatag audit --help
compatag --version
```

`python -m compatag` provides the same CLI.

## MCP

The MCP client starts a local subprocess and communicates over standard input and output. Both entry points start the same stdio server:

```cmd
compatag-mcp
```

```cmd
compatag mcp
```

### Registration

For [Codex CLI](https://developers.openai.com/codex/mcp), registration uses:

```cmd
codex mcp add compatag -- compatag-mcp
```

The executable must be on the client's `PATH`. An absolute path to the installed executable can replace `compatag-mcp`, including an executable inside a virtual environment. General client and Claude Code examples appear in the [README](../README.md#mcp).

### Tools

| Tool | Intended use | Required inputs |
| --- | --- | --- |
| `check_package` | Evaluates one dependency before an addition, upgrade, or deployment. | `requirement`, `target` |
| `audit_manifest` | Checks a project's direct dependencies for one target. | `manifest_text`, `target` |
| `compare_targets` | Evaluates changes before a Python or platform migration. | `manifest_text`, `from_target`, `to_target` |

All three tools query published PyPI information without modifying project files or installing packages.

A `check_package` input:

```json
{
  "requirement": "numpy>=2,<3",
  "target": {
    "python_version": "3.11",
    "implementation": "cpython",
    "platform": "manylinux_2_17_aarch64"
  }
}
```

`implementation` defaults to `cpython`, the only accepted interpreter. An `audit_manifest` input:

```json
{
  "manifest_text": "numpy>=2\nhttpx>=0.28\n",
  "manifest_type": "requirements",
  "target": {
    "python_version": "3.11",
    "platform": "win_amd64"
  },
  "verbosity": "all",
  "max_concurrency": 8
}
```

A `compare_targets` input:

```json
{
  "manifest_text": "numpy>=2\nhttpx>=0.28\n",
  "manifest_type": "requirements",
  "from_target": {
    "python_version": "3.11",
    "platform": "win_amd64"
  },
  "to_target": {
    "python_version": "3.11",
    "platform": "manylinux_2_17_aarch64"
  },
  "verbosity": "changes"
}
```

Manifest tools accept `manifest_type` as `requirements` (the default) or `pyproject`. For pyproject text, `extras` can select optional groups, for example `"extras": ["dev"]`. Extras are invalid with requirements-style text. Both manifest tools accept `max_concurrency` and the same verbosity values as their CLI counterparts.

Manifest tools receive file contents, not local paths. The client reads a file and passes its text as `manifest_text`; Compatag does not read arbitrary paths supplied through MCP.

### Results and errors

Tools return structured results with the same fields and meanings as the core analysis. Package checks include severity, status, selected version and artifact when available, a summary, and notes. Audits include completeness, parsing issues, counts, and findings. Comparisons include both targets, an overall outcome, counts, and requirement changes.

Network and metadata uncertainty appear in result data. Invalid arguments and workloads exceeding limits produce tool errors. MCP has no `--strict` option or per-tool process exit code; clients interpret result severity and outcome directly.

### Limits

Audits and comparisons accept concurrency from 1 to 32, with a default of 8. Comparisons apply the limit to each target audit.

MCP manifest input is limited to 128 KiB of UTF-8 text and 100 parsed requirement entries. Single-package requirement text is limited to 2,048 characters. Optional-group selection accepts up to 32 names of up to 64 characters each. Limits produce errors rather than silently truncating input. The manifest size and entry limits are MCP restrictions, not CLI file limits.

## Common target examples

| Target | Python | Platform |
| --- | --- | --- |
| Windows x64 | `3.11` | `win_amd64` |
| Windows ARM64 | `3.12` | `win_arm64` |
| Linux ARM64, glibc 2.17 baseline | `3.11` | `manylinux_2_17_aarch64` |
| Linux x64, musl 1.2 baseline | `3.12` | `musllinux_1_2_x86_64` |
| macOS 14, Apple silicon | `3.11` | `macosx_14_0_arm64` |

The target should describe the deployment environment. [Compatibility](COMPATIBILITY.md#targets) lists supported versions and platform rules.

## Exit codes and result interpretation

For `check` and `audit`:

| Result | Default exit code | With `--strict` |
| --- | --- | --- |
| PASS | 0 | 0 |
| WARN | 0 | 1 |
| FAIL | 1 | 1 |
| UNKNOWN | 2 | 2 |

For `compare`:

| Outcome | Exit code |
| --- | --- |
| UNCHANGED or IMPROVEMENT | 0 |
| REGRESSION or MIXED | 1 |
| INDETERMINATE | 2 |

CLI argument, target, file, and resource-limit errors return 2. `compare` does not accept `--strict`.

A zero comparison exit code describes relative change, not a clean destination audit. An unchanged failure can exist on both targets. A destination `audit` evaluates its absolute compatibility status; `--verbosity all` also exposes unchanged comparison findings.
