from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version as distribution_version
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from compatag.analyzer import (
    PackageCheckResult,
)
from compatag.analyzer import (
    check_package as analyze_package,
)
from compatag.audit import (
    AuditVerbosity,
    ManifestAuditResult,
)
from compatag.audit import (
    audit_manifest as run_manifest_audit,
)
from compatag.compare import (
    ComparisonVerbosity,
    TargetComparisonResult,
)
from compatag.compare import (
    compare_targets as run_target_comparison,
)
from compatag.manifests import (
    ManifestFormat,
    ParsedManifest,
    parse_pyproject,
    parse_requirements,
)
from compatag.pypi import (
    ProjectSource,
    PyPIClient,
)
from compatag.targets import TargetEnvironment

RequirementText = Annotated[
    str,
    Field(
        min_length=1,
        description=("A PEP 508 Python requirement, for example 'numpy>=2,<3'."),
    ),
]

ManifestText = Annotated[
    str,
    Field(
        min_length=1,
        description=("The full dependency manifest contents. Pass text, not a filesystem path."),
    ),
]

ConcurrencyLimit = Annotated[
    int,
    Field(
        ge=1,
        le=32,
        description=("Maximum number of package checks allowed to run concurrently."),
    ),
]


@dataclass(frozen=True)
class ServerContext:
    project_source: ProjectSource


@asynccontextmanager
async def _server_lifespan(
    _server: MCPServer,
) -> AsyncIterator[ServerContext]:
    async with PyPIClient() as project_source:
        yield ServerContext(project_source=project_source)


_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=True,
)


_SERVER_INSTRUCTIONS = (
    "Compatag analyzes published PyPI distribution compatibility for explicit "
    "CPython deployment targets. Use check_package for one dependency, "
    "audit_manifest for direct dependencies in one manifest, and "
    "compare_targets before changing Python versions or deployment platforms. "
    "Compatag does not resolve transitive dependencies, build source "
    "distributions, or guarantee application runtime success."
)


mcp = MCPServer(
    "compatag",
    title="Compatag",
    description=("Preflight Python package compatibility across deployment targets."),
    instructions=_SERVER_INSTRUCTIONS,
    version=distribution_version("compatag"),
    lifespan=_server_lifespan,
)


@mcp.tool(
    title="Check package compatibility",
    description=(
        "Check one direct PyPI requirement against an explicit CPython "
        "deployment target. Use this before adding, upgrading, pinning, "
        "or diagnosing one dependency. The result describes published "
        "wheel or source-distribution evidence and does not resolve "
        "transitive dependencies."
    ),
    annotations=_TOOL_ANNOTATIONS,
)
async def check_package(
    requirement: RequirementText,
    target: TargetEnvironment,
    ctx: Context[ServerContext],
) -> PackageCheckResult:
    return await analyze_package(
        requirement,
        target,
        ctx.request_context.lifespan_context.project_source,
    )


@mcp.tool(
    title="Audit dependency manifest",
    description=(
        "Audit direct dependencies declared in requirements-style text or "
        "a PEP 621 pyproject against one deployment target. Pass manifest "
        "contents rather than a file path. Use this before deployment when "
        "project-wide compatibility evidence is needed."
    ),
    annotations=_TOOL_ANNOTATIONS,
)
async def audit_manifest(
    manifest_text: ManifestText,
    target: TargetEnvironment,
    ctx: Context[ServerContext],
    manifest_type: ManifestFormat = ManifestFormat.REQUIREMENTS,
    extras: list[str] | None = None,
    verbosity: AuditVerbosity = AuditVerbosity.PROBLEMS,
    max_concurrency: ConcurrencyLimit = 8,
) -> ManifestAuditResult:
    manifest = _parse_manifest(
        manifest_text,
        manifest_type,
        extras,
    )

    return await run_manifest_audit(
        manifest,
        target,
        ctx.request_context.lifespan_context.project_source,
        verbosity=verbosity,
        max_concurrency=max_concurrency,
    )


@mcp.tool(
    title="Compare deployment targets",
    description=(
        "Compare the same direct dependency manifest across two explicit "
        "deployment targets. Use this before changing Python version, "
        "operating system, CPU architecture, libc baseline, container base, "
        "or deployment environment. The result identifies compatibility, "
        "version, artifact, and applicability changes."
    ),
    annotations=_TOOL_ANNOTATIONS,
)
async def compare_targets(
    manifest_text: ManifestText,
    from_target: TargetEnvironment,
    to_target: TargetEnvironment,
    ctx: Context[ServerContext],
    manifest_type: ManifestFormat = ManifestFormat.REQUIREMENTS,
    extras: list[str] | None = None,
    verbosity: ComparisonVerbosity = ComparisonVerbosity.CHANGES,
    max_concurrency: ConcurrencyLimit = 8,
) -> TargetComparisonResult:
    manifest = _parse_manifest(
        manifest_text,
        manifest_type,
        extras,
    )

    return await run_target_comparison(
        manifest,
        from_target,
        to_target,
        ctx.request_context.lifespan_context.project_source,
        verbosity=verbosity,
        max_concurrency=max_concurrency,
    )


def _parse_manifest(
    manifest_text: str,
    manifest_type: ManifestFormat,
    extras: list[str] | None,
) -> ParsedManifest:
    selected_extras = tuple(extras or ())

    if manifest_type is ManifestFormat.REQUIREMENTS:
        if selected_extras:
            raise ToolError("extras can only be selected for pyproject manifests")

        return parse_requirements(manifest_text)

    return parse_pyproject(
        manifest_text,
        extras=selected_extras,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
