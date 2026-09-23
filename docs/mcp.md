# MCP Server

## Purpose

Compatag exposes its deterministic package compatibility engine through a local Model Context Protocol server.

The MCP server is an adapter over the same core used by the command-line interface.

## Transport

The initial server uses MCP stdio.

The client launches Compatag as a subprocess and communicates through the process standard input and standard output streams.

The dedicated launcher is:

```text
compatag-mcp
```

The same server may also be started through:

```text
compatag mcp
```

For MCP client configuration, the dedicated `compatag-mcp` executable is preferred.

## Tool surface

Compatag initially exposes exactly three MCP tools:

```text
check_package
audit_manifest
compare_targets
```

No MCP resources or prompts are required for v0.1.

## check_package

Use `check_package` when evaluating one dependency before adding, upgrading, pinning, or deploying it.

Conceptual input:

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

The result is the same typed `PackageCheckResult` used by the core analyzer.

## audit_manifest

Use `audit_manifest` to analyze the direct dependencies declared in one requirements-style manifest or PEP 621 pyproject.

The tool receives manifest contents, not a filesystem path.

Conceptual input:

```json
{
  "manifest_text": "numpy>=2\nhttpx>=0.28\n",
  "manifest_type": "requirements",
  "target": {
    "python_version": "3.11",
    "implementation": "cpython",
    "platform": "manylinux_2_17_aarch64"
  },
  "verbosity": "problems",
  "max_concurrency": 8
}
```

For pyproject manifests, optional dependency groups may be selected through:

```json
{
  "extras": ["dev", "docs"]
}
```

Extras are not valid for requirements-style manifests.

## compare_targets

Use `compare_targets` before changing:

```text
Python version
operating system
CPU architecture
manylinux baseline
musllinux baseline
container base
deployment environment
```

Conceptual input:

```json
{
  "manifest_text": "numpy\nhttpx\n",
  "manifest_type": "requirements",
  "from_target": {
    "python_version": "3.11",
    "implementation": "cpython",
    "platform": "win_amd64"
  },
  "to_target": {
    "python_version": "3.11",
    "implementation": "cpython",
    "platform": "manylinux_2_17_aarch64"
  },
  "verbosity": "changes"
}
```

## Structured output

Tool functions return Compatag's Pydantic domain models directly.

The MCP Python SDK derives output schemas from these return annotations and returns corresponding structured tool content.

Compatag does not maintain a second MCP-specific result schema.

## Server lifespan

One `PyPIClient` is created when the MCP server starts.

The client is shared across tool calls for the lifetime of the server and is closed when the server stops.

This allows HTTP connection pooling without creating a new client for every MCP request.

Comparison retains its own operation-scoped metadata memoization on top of the shared PyPI client.

## Tool annotations

Every Compatag MCP tool is declared:

```text
read-only
open-world
```

The tools do not modify local or remote state.

They are open-world because they query live PyPI repository data.

## Filesystem boundary

MCP tools do not accept local manifest paths.

The MCP host is responsible for reading a file and supplying its contents to Compatag.

This keeps the tool interface identical for local stdio and future remote HTTP deployment.

## Error handling

Expected compatibility uncertainty is returned as structured Compatag data.

Examples include:

```text
network_error
metadata_error
indeterminate_marker
indeterminate_requires_python
```

Invalid combinations of MCP arguments may raise an MCP `ToolError` so the calling model can correct the request.

Unexpected implementation errors are not converted into compatibility results.

## Scope

The MCP interface does not change Compatag's analysis scope.

Compatag does not:

- resolve transitive dependencies;
- execute packages;
- build source distributions;
- guarantee runtime compatibility;
- fetch arbitrary direct URLs;
- access arbitrary local filesystem paths.
