# Target Comparison

## Purpose

Target comparison evaluates the same parsed dependency manifest against two deployment targets and reports what changes.

Comparison does not implement package compatibility itself.

It compares complete package-audit results produced by the existing audit layer.

## Data flow

```text
                        ParsedManifest
                        /            \
                       v              v
                 From Target      To Target
                       |              |
                       v              v
                    audit          audit
                       \              /
                        \            /
                         v          v
                          comparison
                              |
                              v
                    TargetComparisonResult
```

Both audits share one operation-scoped project metadata source.

## Compatibility impact

Each requirement comparison has one directional impact:

```text
UNCHANGED
IMPROVEMENT
REGRESSION
INDETERMINATE
```

Known severity uses the ordering:

```text
PASS
WARN
FAIL
```

Moving toward PASS is an improvement.

Moving toward FAIL is a regression.

Any comparison involving UNKNOWN is indeterminate.

UNKNOWN is not treated as better or worse than a known compatibility state.

## Operational changes

Compatibility impact is separate from other changes.

A requirement comparison also records:

```text
severity_changed
status_changed
selected_version_changed
artifact_changed
applicability_changed
```

For example, moving from a Windows wheel to a Linux wheel may be:

```text
PASS -> PASS

impact:
UNCHANGED

artifact_changed:
true
```

The wheel changed, but compatibility did not regress.

## Applicability

Environment markers may cause a dependency to apply on one target but not another.

Example:

```text
colorama ; sys_platform == "win32"
```

Windows to Linux may therefore produce:

```text
status_changed = true
applicability_changed = true
impact = unchanged
```

when both sides remain PASS.

## Overall outcome

The comparison result uses:

```text
UNCHANGED
IMPROVEMENT
REGRESSION
MIXED
INDETERMINATE
```

Known improvements and regressions together produce MIXED.

A known regression remains REGRESSION when unrelated uncertainty also exists.

Improvements are only reported as an overall IMPROVEMENT when the remaining comparison is sufficiently complete.

If improvement exists alongside uncertainty, the overall result is INDETERMINATE.

## Incomplete manifests

The same ParsedManifest is used for both targets.

If the manifest contains unresolved dependency information, an apparent improvement cannot be claimed for the whole project.

Example:

```text
known package:
WARN -> PASS

unresolved:
-r private.txt

overall:
INDETERMINATE
```

A confirmed regression still remains a regression:

```text
known package:
PASS -> FAIL

unresolved:
-r private.txt

overall:
REGRESSION
```

## Project Requires-Python

Project-level Python compatibility is compared separately from package requirements.

The result records both project-Python checks and their directional impact.

A migration may therefore regress even if every external dependency remains
compatible.

## Shared PyPI metadata

Target comparison uses an operation-scoped memoizing project source.

The same normalized project is retrieved only once during one comparison,
even when:

```text
multiple version constraints reference it
both targets require it
```

Only project metadata is shared.

Compatibility analysis is recalculated independently for each target.

## In-flight request coalescing

The memoizing source stores the asyncio task representing a project lookup.

If multiple package checks request the same project concurrently, they await the same task rather than issuing duplicate HTTP requests.

The cache exists only for the lifetime of one comparison operation.

It is not a persistent PyPI cache.

## Concurrency

Each audit retains the normal bounded package-check concurrency.

The from-target and to-target audits run sequentially while sharing memoized project data.

This prevents target comparison from accidentally doubling the configured outbound concurrency limit.

## Deterministic ordering

Both underlying audits use ALL verbosity internally.

Requirement occurrences are compared in original manifest order.

Network completion order therefore does not affect serialized comparison order.

## Verbosity

Two comparison output modes exist:

```text
changes
all
```

`changes` is the default.

It retains requirement comparisons when any of these are true:

```text
compatibility impact changed
status changed
selected version changed
artifact changed
applicability changed
```

A completely identical clean result is suppressed.

`all` returns every manifest occurrence.

Aggregate counts always describe every occurrence regardless of output verbosity.

## Caching boundary

The comparison layer caches repository data:

```text
ProjectDistributions
```

It does not cache:

```text
PackageCheckResult
```

because a package result is target-specific.

## Architectural boundary

```text
             manifests.py
                  |
                  v
            ParsedManifest
                  |
                  v
              compare.py
              /        \
             v          v
         audit.py    audit.py
             \          /
              v        v
              analyzer.py
                   |
                   v
              ProjectSource
```

Comparison does not duplicate:

- wheel-tag matching;
- release selection;
- Requires-Python evaluation;
- manifest parsing;
- PyPI response parsing.
