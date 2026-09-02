# Compatag Compatibility Model

## Compatibility tags

Python wheels describe their runtime compatibility using a three-part tag:

```
{python tag}-{abi tag}-{platform tag}
```

For example:

```
cp311-cp311-manylinux_2_17_aarch64
```

Compatag represents a target environment and generates the ordered set of wheel tags that the target accepts.

A wheel is potentially compatible when at least one of its published compatibility tags matches one of the target's accepted tags.

Artifact inspection and wheel matching are implemented in later milestones.

## Target environment

A target currently contains:

- a Python major/minor version
- the CPython implementation
- a platform compatibility target.

Example:

```
Python: 3.11
Implementation: cpython
Platform: manylinux_2_17_aarch64
```

Compatag models normal GIL-enabled CPython release builds.

Debug and free-threaded CPython ABIs are outside the initial scope.

## Cross-target generation

Compatag must not derive compatibility from the machine on which Compatag itself is running.

The same Compatag process must be able to evaluate targets such as:

```
win_amd64
manylinux_2_17_aarch64
musllinux_1_2_x86_64
macosx_14_0_arm64
```

regardless of the host operating system.

For this reason, target Python versions, ABIs, and platforms are supplied explicitly to the packaging tag-generation APIs.

## Windows

Windows targets currently use their exact wheel platform tag:

```
win32
win_amd64
win_arm64
```

## manylinux

A target such as:

```
manylinux_2_28_x86_64
```

represents a compatible glibc 2.28 x86-64 environment.

Wheels targeting an older supported glibc baseline are accepted, while wheels requiring a newer baseline are not.

Legacy manylinux aliases are included where defined:

```
manylinux1 = manylinux_2_5
manylinux2010 = manylinux_2_12
manylinux2014 = manylinux_2_17
```

Compatag currently models glibc major version 2.

## musllinux

musllinux targets follow the version compatibility model defined for musl-based Linux systems.

For example, a musl 1.2 target accepts compatible wheels targeting musl 1.2, 1.1, or 1.0, but not 1.3.

## macOS

macOS platform compatibility is delegated to `packaging.tags.mac_platforms`.

Modern macOS targets use platform forms such as:

```
macosx_14_0_arm64
macosx_13_0_x86_64
```

The generated platform set may include compatible older macOS targets and universal2 tags.

## Generic Linux tags

Generic tags such as:

```
linux_x86_64
linux_aarch64
```

are outside the initial Compatag target model.

Compatag's initial PyPI-oriented analysis uses portable manylinux and musllinux policy tags instead.

## Compatibility is not execution success

A matching wheel tag means that the distribution declares compatibility with the modeled Python ABI and platform.
It does not prove that:

- application code is correct
- external system libraries are installed
- GPU drivers are compatible
- package initialization succeeds
- an sdist can be compiled successfully.

Compatag reports published distribution compatibility, not guaranteed runtime success.
