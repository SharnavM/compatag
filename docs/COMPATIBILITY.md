# Compatibility

Compatag checks whether published PyPI artifacts declare compatibility with an explicit target. A matching wheel is evidence about a distribution's Python and platform support. It does not prove that installation, package initialization, or application execution will succeed.

## Targets

A target contains a CPython major/minor version and a wheel platform tag. The target model accepts CPython 3.9 and newer Python 3 release lines, in forms such as `3.11`. Patch versions such as `3.11.9` are not accepted. Running Compatag itself requires Python 3.11 or newer.

Targets model standard CPython release builds with the GIL. Debug builds, free-threaded builds, and other interpreters are outside the current scope. The host machine's Python version and platform do not determine the target.

| Platform family | Accepted target forms and behavior |
| --- | --- |
| Windows | `win32`, `win_amd64`, and `win_arm64`; platform tags match the selected architecture. |
| manylinux | `manylinux_2_<minor>_<architecture>`; accepts supported older glibc baselines and their applicable legacy wheel aliases. |
| musllinux | `musllinux_<major>_<minor>_<architecture>`; accepts older minor baselines within the same musl major version. |
| macOS | `macosx_<major>_<minor>_x86_64` or `macosx_<major>_<minor>_arm64`; includes compatible older platform and universal2 wheel tags. macOS 11+ target tags require a zero minor component, such as `macosx_14_0_arm64`. |

Linux architectures are `x86_64`, `i686`, `aarch64`, `armv7l`, `ppc64`, `ppc64le`, `s390x`, `loongarch64`, and `riscv64`. manylinux targets require glibc 2.5+ for `x86_64` and `i686`, or 2.17+ for the other accepted architectures. Generic `linux_*` targets are not supported. Legacy names such as `manylinux2014` are recognized in wheel tags, not as target inputs.

## Wheels and release selection

A wheel is compatible when its Python, ABI, and platform tags match an accepted target tag and its `Requires-Python` metadata permits the target. ABI tags describe the Python binary interface required by the wheel. Compatible stable-ABI wheels are included.

Platform-independent wheels, such as `py3-none-any`, receive `universal_wheel_available` when their Python constraints also match. A macOS universal2 wheel still has a platform requirement.

Compatag considers matching releases from newest to oldest, using standard Python version-specifier and prerelease rules. Within a release, a compatible wheel is preferred. A newer release with an applicable source distribution is not skipped merely because an older release has a wheel. An uncertain candidate may produce `UNKNOWN` rather than an older successful result.

When the selected release has an applicable source distribution but no compatible wheel, the result is `WARN` with status `source_build_required`. Compatag does not build the source distribution or check whether compilers, system libraries, or build dependencies are available.

Yanked files are excluded from successful selection, including exact pins. If only otherwise usable yanked artifacts remain, the result is `FAIL` with status `yanked_only`. The published yank reason is retained when available.

## Python requirements and markers

`Requires-Python` is evaluated across the entire target minor release line. For target `3.11`, the range is `>=3.11,<3.12`.

- A constraint covering the whole range is compatible.
- A constraint excluding the whole range is incompatible.
- A constraint matching only part of the range, such as `>=3.11.5`, is indeterminate.

The same rules apply to the project's `requires-python` field during an audit. Missing constraints add no Python restriction. Invalid metadata produces uncertainty rather than a successful compatibility claim.

Environment markers use target information. Supported values include `python_version`, `implementation_name`, `os_name`, `sys_platform`, `platform_system`, `platform_machine`, and `platform_python_implementation`.

Markers containing `python_full_version`, `implementation_version`, `platform_release`, `platform_version`, `extra`, `extras`, or `dependency_groups` are indeterminate because the target does not supply that context. A requirement excluded by a supported marker receives `PASS` with status `not_applicable`.

## Package and audit results

Structured output uses lowercase values, such as `pass` and `unknown`. CLI summaries display severity in uppercase.

| Severity | Meaning |
| --- | --- |
| PASS | A compatible wheel is available, or the requirement does not apply to the target. |
| WARN | An applicable source distribution is available but a source build is required. Audits can also warn about non-blocking manifest issues. |
| FAIL | Evidence establishes a problem, such as a missing project, no matching release, no compatible distribution, or only usable yanked artifacts. |
| UNKNOWN | Available information is insufficient, such as a network failure, invalid metadata, unsupported requirement, or unresolved marker. |

Audit severity combines package findings, project Python compatibility, and parsing issues in this order: `FAIL`, `UNKNOWN`, `WARN`, `PASS`. A confirmed failure remains `FAIL` even if other entries are unresolved. Without a failure, an incomplete manifest makes the audit `UNKNOWN`.

Package counts include every manifest occurrence. `unique_checks` counts distinct analyses. Output filtering does not change aggregate counts. [Manifests](MANIFESTS.md) explains parsing issues and completeness.

## Target comparisons

Comparison measures the change from the source target to the destination target. Moving from `FAIL` toward `PASS` is an improvement; moving toward `FAIL` is a regression. Any package comparison involving `UNKNOWN` is indeterminate. Project Python compatibility also contributes to the overall outcome.

| Outcome | Meaning |
| --- | --- |
| UNCHANGED | No severity improvement or regression and no unresolved comparison. |
| IMPROVEMENT | At least one improvement, with no regression or uncertainty. |
| REGRESSION | At least one regression and no improvement; unrelated uncertainty does not hide the regression. |
| MIXED | Both confirmed improvements and regressions exist. |
| INDETERMINATE | Uncertainty or incomplete input prevents a conclusion, with no confirmed regression. |

Version, artifact, status, and applicability changes are reported separately. A Windows wheel changing to a Linux wheel can remain `PASS` on both sides. A marker can make a dependency inapplicable on the destination without causing a regression.

`UNCHANGED` does not mean both targets pass: a dependency that fails on both targets can be unchanged. [Usage](USAGE.md#exit-codes-and-result-interpretation) explains exit codes and output options.

## Evidence limits

- Checks cover direct dependencies independently; they do not resolve transitive dependencies or prove that all requirements can be installed together.
- Analysis uses published PyPI metadata, which can change. Distribution files are not downloaded, built, or executed.
- External libraries, GPU drivers, application behavior, and successful source builds are not verified.
- Private indexes, arbitrary direct URLs, and local distributions are outside the current analysis scope.
- Repository failures and oversized PyPI responses produce uncertainty. The default response limit is 16 MiB per project; [usage limits](USAGE.md#limits) describe configurable concurrency and MCP input bounds.
