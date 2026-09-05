# Package Compatibility Analysis

## Purpose

Package analysis combines a parsed Python requirement, published PyPI
distribution metadata, and a Compatag target environment.

The analyzer answers whether an applicable published distribution can be
used for the target without requiring a source build.

## Inputs

A package check requires:

```text
PEP 508 requirement
TargetEnvironment
PyPIClient
```

Example:

```
numpy>=2,<3

CPython 3.11
manylinux_2_17_aarch64
```

## Selection sequence

Compatag evaluates package candidates in this order:

```
parse requirement
        |
        v
evaluate environment marker
        |
        v
retrieve project from PyPI
        |
        v
filter releases by version specifier
        |
        v
newest applicable release first
        |
        v
ignore yanked files
        |
        v
evaluate wheel tags and Requires-Python
        |
        +-- compatible wheel -> PASS
        |
        +-- indeterminate wheel -> UNKNOWN
        |
        +-- usable sdist -> WARN
        |
        +-- indeterminate sdist -> UNKNOWN
        |
        v
try older matching release
```

If no non-yanked candidate is usable, Compatag checks whether an otherwise usable yanked artifact exists.

Yanked artifacts do not produce a successful result in Compatag v0.1.

## Version constraints

PEP 440 version matching and prerelease behavior are delegated to PyPA's `packaging` library.

Compatag uses `SpecifierSet.filter()` so prereleases are considered only according to packaging's normal prerelease-selection behavior.

Arbitrary equality using `===` is outside the initial scope.

## Requires-Python

A Compatag target identifies Python by major and minor version rather than a specific micro release.

Therefore a target such as:

```
CPython 3.11
```

is modeled for Requires-Python analysis as:

```
=3.11,<3.12
```

If the entire target range satisfies Requires-Python, the file is compatible.

If the target range and Requires-Python are disjoint, the file is incompatible.

If only part of the target minor release line satisfies Requires-Python, Compatag returns an indeterminate result.

Example:

```
Target:
3.11

Requires-Python:

> =3.11.5

Result:
INDETERMINATE_REQUIRES_PYTHON
```

Compatag does not substitute the Python micro version of the machine on which it is running.

## Environment markers

Markers are evaluated against the target rather than the Compatag host.
Supported target-derived marker values include:

```
python_version
implementation_name
os_name
sys_platform
platform_system
platform_machine
platform_python_implementation
```

Markers requiring target information that Compatag does not model are reported as indeterminate.

Examples include:

```
python_full_version
implementation_version
platform_release
platform_version
extra
extras
dependency_groups
```

## Wheel compatibility

Wheel tags are parsed with:

```
packaging.utils.parse_wheel_filename
```

and compared against:

```
compatibility_tags(target)
```

Selection among multiple compatible wheels is delegated to PyPA's compatible tag selector so target preference ordering is preserved.

## Universal wheels

A compatible wheel containing a tag with:

```
ABI: none
Platform: any
```

is reported as:

```
UNIVERSAL_WHEEL_AVAILABLE
```

## Source distributions

A source distribution is considered a fallback artifact when its Requires-Python metadata is compatible with the target.

Compatag does not attempt to build it.

Therefore the presence of an applicable sdist without a compatible wheel is
reported as:

```
SOURCE_BUILD_REQUIRED
```

This is a warning rather than proof that installation will fail.

## Yanked files

Compatag v0.1 does not return successful compatibility results from yanked files.

A yanked artifact is considered only after all non-yanked matching releases have been exhausted.

If a yanked artifact would otherwise be usable, Compatag reports:

```
YANKED_ONLY
```

and preserves the published yank reason when available.

## Extras

Requirement extras are parsed but their transitive dependencies are not resolved in v0.1.

For example:

```
requests[socks]>=2
```

checks the published `requests` distribution and includes a note that dependencies introduced by the `socks` extra were not analyzed.

## Direct URLs

Direct URL requirements are outside the PyPI-only v0.1 analysis boundary:

```
package @ https://example.com/package.whl
```

Compatag does not fetch or execute arbitrary package URLs.

## Result severity

Compatag uses four severity levels:

```
PASS
WARN
FAIL
UNKNOWN
```

`UNKNOWN` is intentionally distinct from failure.

It means Compatag lacks enough reliable information to make the requested compatibility claim.
