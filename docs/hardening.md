# Runtime Hardening

## Purpose

Compatag performs external repository lookups and can analyze manifests supplied by command-line users or MCP clients.

Runtime hardening places explicit bounds around those workloads without changing compatibility semantics.

## Analysis concurrency

Project audits use bounded asynchronous package checks.

The core accepts:

```text
1 <= max_concurrency <= 32
```

The normal default remains:

```text
8
```

The upper bound applies regardless of whether the audit was requested through the CLI, MCP, or Python API.

## MCP manifest limits

MCP manifest tools limit one manifest payload to:

```text
128 KiB UTF-8
```

and at most:

```text
100 parsed requirement entries
```

These are workload limits rather than Python packaging-format restrictions.

The core manifest parser itself does not truncate manifests.

If an MCP workload exceeds a limit, the tool returns an explicit error rather than silently dropping dependency entries.

## PyPI response limit

One PyPI Simple API project response is limited to:

```text
16 MiB
```

Compatag checks both a declared Content-Length and the bytes received while streaming the response.

A response that exceeds the bound is rejected rather than fully buffered.

## HTTP connection pool

Compatag's internally created HTTP client uses bounded connection resources.

The configured limits are:

```text
maximum connections:           16
maximum keep-alive connections: 8
```

Normal audit concurrency remains lower than this by default.

## PyPI cache

A PyPIClient maintains a bounded in-memory cache of successful project
responses.

Default policy:

```text
TTL:             5 minutes
maximum entries: 256
```

The cache exists only for the lifetime of that PyPIClient.

CLI commands therefore receive a short-lived cache, while a long-lived MCP server can reuse metadata across several tool calls.

The cache is not persistent and does not survive process restart.

## Failed requests

Network errors, malformed repository data, and unsuccessful HTTP responses are not inserted into the successful-response cache.

Compatag does not currently perform automatic request retries.

Expected repository failures continue to surface through the existing structured compatibility result model.

## In-flight request coalescing

If multiple concurrent analyses request the same normalized project name, they await one shared PyPI lookup rather than issuing duplicate requests.

Cancelling one waiter does not intentionally cancel the shared underlying lookup for every other waiter.

## MCP stdio safety

Standard output belongs exclusively to MCP protocol messages.

Compatag does not use `print()` for MCP server diagnostics.

Any future server diagnostics must use Python's logging module, which writes to standard error under the MCP stdio server configuration.

An integration test launches the actual MCP server as a subprocess and performs tool discovery over stdio. This protects against import-time or startup output corrupting the protocol.

## CI

The test workflow runs on:

```text
Windows
Ubuntu
```

for:

```text
Python 3.11
Python 3.12
Python 3.13
Python 3.14
```

Separate quality checks run Ruff, Ruff formatting, mypy, coverage, dependency consistency checks, package building, and distribution metadata validation.

Normal CI does not depend on live PyPI availability.
