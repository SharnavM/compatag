# Command-Line Interface

## Purpose

Compatag exposes its deterministic compatibility engine through a command-line
interface.

The CLI is a thin adapter over the core library.

It does not implement package compatibility, manifest parsing, PyPI protocol, or target-comparison rules itself.

## Commands

Compatag currently provides:

```text
compatag check
compatag audit
compatag compare
```

Global version information is available through:

```cmd
compatag --version
```

## check

Check one PEP 508 requirement against one deployment target.

```cmd
compatag check "numpy>=2,<3" --python 3.11 --platform manylinux_2_17_aarch64
```

Machine-readable output:

```cmd
compatag check "numpy>=2,<3" --python 3.11 --platform manylinux_2_17_aarch64 --json
```

Strict mode treats WARN results as non-zero:

```cmd
compatag check demo --python 3.11 --platform win_amd64 --strict
```

## audit

Audit a dependency manifest against one target.

```cmd
compatag audit requirements.txt --python 3.11 --platform win_amd64
```

pyproject example:

```cmd
compatag audit pyproject.toml --python 3.11 --platform manylinux_2_17_aarch64
```

Optional dependency groups may be selected repeatedly:

```cmd
compatag audit pyproject.toml --extra postgres --extra cli --python 3.11 --platform manylinux_2_17_aarch64
```

Audit verbosity:

```text
problems
all
```

`problems` is the default and suppresses clean PASS findings.

Example:

```cmd
compatag audit requirements.txt --python 3.11 --platform win_amd64 --verbosity all
```

Concurrency can be limited:

```cmd
compatag audit requirements.txt --python 3.11 --platform win_amd64 --concurrency 4
```

## compare

Compare the same manifest across two deployment targets.

```cmd
compatag compare requirements.txt --from-python 3.11 --from-platform win_amd64 --to-python 3.11 --to-platform manylinux_2_17_aarch64
```

Windows CMD multiline form:

```cmd
compatag compare requirements.txt ^
  --from-python 3.11 ^
  --from-platform win_amd64 ^
  --to-python 3.11 ^
  --to-platform manylinux_2_17_aarch64
```

Comparison verbosity:

```text
changes
all
```

`changes` is the default.

It preserves compatibility, status, selected-version, artifact, and applicability changes while suppressing completely identical requirement results.

## Manifest type detection

Compatag automatically recognizes:

```text
pyproject.toml
requirements.txt
requirements-*.txt
requirements_*.txt
requirements.in
```

Other filenames require an explicit override:

```cmd
compatag audit dependencies.list --type requirements --python 3.11 --platform win_amd64
```

or:

```cmd
compatag audit project-config.toml --type pyproject --python 3.11 --platform win_amd64
```

## Extras

`--extra` applies only to pyproject manifests.

The option may be repeated:

```cmd
--extra dev --extra docs
```

Using `--extra` with a requirements-style manifest is a CLI usage error.

## JSON

All analysis commands support:

```text
--json
```

JSON output is serialized directly from Compatag's typed domain result models.

Human-readable output may omit lower-level metadata for readability, while JSON retains the complete structured result.

## Exit codes

Analysis commands use:

```text
0 = usable result
1 = confirmed compatibility problem
2 = indeterminate result or CLI/input problem
```

For `check` and `audit`:

```text
PASS              -> 0
WARN              -> 0
WARN + --strict   -> 1
FAIL              -> 1
UNKNOWN           -> 2
```

For `compare`:

```text
UNCHANGED       -> 0
IMPROVEMENT     -> 0
REGRESSION      -> 1
MIXED           -> 1
INDETERMINATE   -> 2
```

Argument-parser syntax errors also use the conventional process exit code 2.

## Target arguments

Targets use CPython major/minor versions and explicit wheel platform tags.

Examples:

```text
--python 3.11 --platform win_amd64
--python 3.12 --platform win_arm64
--python 3.11 --platform manylinux_2_17_aarch64
--python 3.12 --platform musllinux_1_2_x86_64
--python 3.11 --platform macosx_14_0_arm64
```

Compatag does not infer the deployment target from the machine running the CLI.

## File encoding

Manifest files are read as UTF-8 with optional UTF-8 BOM handling.

The CLI passes manifest contents to the existing parser layer.

## Architectural boundary

```text
command line
     |
     v
   cli.py
     |
     +------> targets.py
     |
     +------> manifests.py
     |
     +------> analyzer.py
     |
     +------> audit.py
     |
     +------> compare.py
```

`cli.py` performs argument handling, file loading, result presentation, and exit-code mapping.

Compatibility semantics remain in the core modules.
