# Manifest Auditing

## Purpose

Manifest auditing combines a parsed dependency manifest, a deployment target, and package compatibility analysis.

The audit layer does not parse manifest file syntax and does not directly interpret PyPI wire responses.

## Data flow

```text
manifest text
      |
      v
manifest parser
      |
      v
ParsedManifest
      |
      v
audit_manifest()
      |
      +-- project Requires-Python
      |
      +-- package check
      +-- package check
      +-- package check
      |
      v
ManifestAuditResult
```

## Known and unknown dependencies

A manifest can contain valid dependencies while also containing constructs Compatag cannot fully interpret.

For example:

```text
requests>=2
numpy>=2
-r private.txt
```

Compatag audits the two statically known dependencies and preserves the unsupported include directive as a manifest issue.

The result is incomplete even if both visible dependencies pass.

## Overall severity

Audit severity follows this precedence:

```text
FAIL
UNKNOWN
WARN
PASS
```

A confirmed failure takes precedence over incomplete information.

For example:

```text
known dependency fails
+
manifest contains unsupported include

=> FAIL
```

A manifest error with no confirmed failure produces:

```text
UNKNOWN
```

A warning such as a source-build requirement or non-blocking manifest issue produces:

```text
WARN
```

when no failure or uncertainty exists.

## Project Requires-Python

For pyproject manifests, Compatag evaluates the project's own `requires-python` constraint against the target.

The same CPython minor-release range semantics used for package distribution metadata are used here.

For example:

```text
target:
CPython 3.11

project:
requires-python = ">=3.12"

result:
INCOMPATIBLE
```

A micro-version-dependent constraint such as:

```text
>=3.11.5
```

is indeterminate for a target that only specifies Python 3.11.

Compatag does not substitute the Python micro version of the machine running the audit.

## Deduplication

Equivalent requirement checks are executed once.

The analysis identity includes:

```text
normalized project name
normalized extras
version specifier
environment marker
direct URL
```

Source occurrences remain distinct in the final report.

For example:

```text
line 4:  demo>=1
line 19: demo >=1
```

may produce:

```text
requirements_found = 2
unique_checks = 1
```

while retaining two source findings.

## Concurrency

Package checks are asynchronous and use bounded concurrency.

The default maximum number of simultaneously running checks is:

```text
8
```

A semaphore enforces the limit.

Python's structured `TaskGroup` waits for all scheduled checks and propagates unexpected programming failures rather than converting them into ordinary compatibility results.

Expected PyPI lookup problems continue to be handled by the package analyzer as structured UNKNOWN results.

## Deterministic ordering

Network requests may complete in any order.

Audit findings are reconstructed in original manifest order after all unique checks complete.

The serialized result therefore does not depend on network timing.

## Verbosity

Two output modes are supported:

```text
problems
all
```

`problems` is the default.

It returns:

```text
WARN
FAIL
UNKNOWN
PASS results containing notes
```

while suppressing clean PASS findings.

`all` returns every manifest occurrence.

Aggregate counts are always calculated from every finding regardless of verbosity.

## Manifest issues

Parser issues are always retained in the audit result.

Manifest ERROR issues make the audit UNKNOWN unless a confirmed compatibility failure already exists.

Manifest WARNING issues make an otherwise clean audit WARN.

## Result counts

Package counts represent manifest occurrences rather than network requests.

`unique_checks` separately reports the number of distinct package analyses actually executed.

This distinction avoids losing source-level information while still allowing duplicate analysis work to be eliminated.

## Architectural boundary

```text
manifests.py
     |
     v
ParsedManifest
     |
     v
audit.py
     |
     +------> analyzer.py
     |
     v
ManifestAuditResult
```

`audit.py` coordinates existing domain components.

It must not duplicate wheel-tag, release-selection, requirements-file, or PyPI protocol logic.
