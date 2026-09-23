from __future__ import annotations

import asyncio
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from compatag.analyzer import (
    CheckSeverity,
    PackageCheckResult,
    check_package,
)
from compatag.audit import (
    AuditVerbosity,
    ManifestAuditResult,
    audit_manifest,
)
from compatag.compare import (
    ComparisonOutcome,
    ComparisonVerbosity,
    TargetComparisonResult,
    compare_targets,
)
from compatag.manifests import (
    ManifestFormat,
    ManifestIssue,
    ManifestRequirement,
    ParsedManifest,
    parse_pyproject,
    parse_requirements,
)
from compatag.pypi import PyPIClient
from compatag.targets import TargetEnvironment


class CLIError(RuntimeError):
    """User-facing CLI input or file error."""


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="compatag",
        description=("Preflight Python package compatibility across deployment targets."),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('compatag')}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
    )

    check_parser = subparsers.add_parser(
        "check",
        help=("Check one Python requirement against a deployment target."),
    )

    check_parser.add_argument(
        "requirement",
        help=("PEP 508 requirement, for example 'numpy>=2,<3'."),
    )

    _add_target_arguments(check_parser)

    check_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON output.",
    )

    check_parser.add_argument(
        "--strict",
        action="store_true",
        help=("Treat compatibility warnings as a non-zero result."),
    )

    audit_parser = subparsers.add_parser(
        "audit",
        help=("Audit a Python dependency manifest against one deployment target."),
    )

    _add_manifest_arguments(audit_parser)

    _add_target_arguments(audit_parser)

    audit_parser.add_argument(
        "--verbosity",
        choices=[verbosity.value for verbosity in AuditVerbosity],
        default=(AuditVerbosity.PROBLEMS.value),
        help=("Show only notable package findings or every requirement."),
    )

    audit_parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        metavar="N",
        help=("Maximum concurrent package checks (default: 8)."),
    )

    audit_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON output.",
    )

    audit_parser.add_argument(
        "--strict",
        action="store_true",
        help=("Treat compatibility warnings as a non-zero result."),
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help=("Compare one manifest across two deployment targets."),
    )

    _add_manifest_arguments(compare_parser)

    compare_parser.add_argument(
        "--from-python",
        required=True,
        dest="from_python",
        metavar="VERSION",
        help=("Source CPython major.minor version, for example 3.11."),
    )

    compare_parser.add_argument(
        "--from-platform",
        required=True,
        dest="from_platform",
        metavar="PLATFORM",
        help="Source wheel platform tag.",
    )

    compare_parser.add_argument(
        "--to-python",
        required=True,
        dest="to_python",
        metavar="VERSION",
        help=("Destination CPython major.minor version."),
    )

    compare_parser.add_argument(
        "--to-platform",
        required=True,
        dest="to_platform",
        metavar="PLATFORM",
        help="Destination wheel platform tag.",
    )

    compare_parser.add_argument(
        "--verbosity",
        choices=[verbosity.value for verbosity in ComparisonVerbosity],
        default=(ComparisonVerbosity.CHANGES.value),
        help=("Show changed requirements only or every comparison."),
    )

    compare_parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        metavar="N",
        help=("Maximum concurrent package checks within each audit (default: 8)."),
    )

    compare_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit structured JSON output.",
    )

    subparsers.add_parser(
        "mcp",
        help="Run the local MCP server over stdio.",
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "mcp":
        from compatag.mcp_server import main as run_mcp_server

        run_mcp_server()
        return 0

    try:
        if args.command == "check":
            return asyncio.run(_run_check(args))

        if args.command == "audit":
            return asyncio.run(_run_audit(args))

        if args.command == "compare":
            return asyncio.run(_run_compare(args))

        raise CLIError(f"unknown command: {args.command}")

    except CLIError as exc:
        print(
            f"compatag: error: {exc}",
            file=sys.stderr,
        )
        return 2


def _add_target_arguments(
    parser: ArgumentParser,
) -> None:
    parser.add_argument(
        "--python",
        required=True,
        dest="python_version",
        metavar="VERSION",
        help=("Target CPython major.minor version, for example 3.11."),
    )

    parser.add_argument(
        "--platform",
        required=True,
        metavar="PLATFORM",
        help=("Target wheel platform tag, for example win_amd64 or manylinux_2_17_aarch64."),
    )


def _add_manifest_arguments(
    parser: ArgumentParser,
) -> None:
    parser.add_argument(
        "manifest",
        help=("Path to requirements.txt-style input or pyproject.toml."),
    )

    parser.add_argument(
        "--type",
        dest="manifest_type",
        choices=[manifest_format.value for manifest_format in ManifestFormat],
        metavar="TYPE",
        help=("Manifest type override: requirements or pyproject."),
    )

    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="NAME",
        help=("Include a pyproject optional dependency group. May be repeated."),
    )


async def _run_check(
    args: Namespace,
) -> int:
    target = _target(
        args.python_version,
        args.platform,
    )

    async with PyPIClient() as client:
        result = await check_package(
            args.requirement,
            target,
            client,
        )

    _print_check_result(
        result,
        json_output=args.json_output,
    )

    return _analysis_exit_code(
        result.severity,
        strict=args.strict,
    )


async def _run_audit(
    args: Namespace,
) -> int:
    manifest = _load_manifest(
        args.manifest,
        manifest_type=args.manifest_type,
        extras=args.extra,
    )

    target = _target(
        args.python_version,
        args.platform,
    )

    verbosity = AuditVerbosity(args.verbosity)

    async with PyPIClient() as client:
        result = await audit_manifest(
            manifest,
            target,
            client,
            verbosity=verbosity,
            max_concurrency=args.concurrency,
        )

    _print_audit_result(
        result,
        json_output=args.json_output,
    )

    return _analysis_exit_code(
        result.severity,
        strict=args.strict,
    )


async def _run_compare(
    args: Namespace,
) -> int:
    manifest = _load_manifest(
        args.manifest,
        manifest_type=args.manifest_type,
        extras=args.extra,
    )

    from_target = _target(
        args.from_python,
        args.from_platform,
    )

    to_target = _target(
        args.to_python,
        args.to_platform,
    )

    verbosity = ComparisonVerbosity(args.verbosity)

    async with PyPIClient() as client:
        result = await compare_targets(
            manifest,
            from_target,
            to_target,
            client,
            verbosity=verbosity,
            max_concurrency=args.concurrency,
        )

    _print_comparison_result(
        result,
        json_output=args.json_output,
    )

    return _comparison_exit_code(result.outcome)


def _target(
    python_version: str,
    platform: str,
) -> TargetEnvironment:
    try:
        return TargetEnvironment(
            python_version=python_version,
            platform=platform,
        )
    except ValidationError as exc:
        raise CLIError(_validation_message(exc)) from exc


def _validation_message(
    error: ValidationError,
) -> str:
    messages: list[str] = []

    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])

        message = item["msg"]

        if location:
            messages.append(f"{location}: {message}")
        else:
            messages.append(message)

    return "; ".join(messages)


def _load_manifest(
    path_text: str,
    *,
    manifest_type: str | None,
    extras: Sequence[str],
) -> ParsedManifest:
    path = Path(path_text)

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CLIError(f"could not read '{path}': {exc}") from exc

    manifest_format = (
        ManifestFormat(manifest_type)
        if manifest_type is not None
        else _detect_manifest_format(path)
    )

    if extras and manifest_format is ManifestFormat.REQUIREMENTS:
        raise CLIError("--extra is only valid for pyproject manifests")

    if manifest_format is ManifestFormat.REQUIREMENTS:
        return parse_requirements(text)

    return parse_pyproject(
        text,
        extras=extras,
    )


def _detect_manifest_format(
    path: Path,
) -> ManifestFormat:
    name = path.name.lower()

    if name == "pyproject.toml":
        return ManifestFormat.PYPROJECT

    if (
        name == "requirements.txt"
        or name.startswith("requirements-")
        or name.startswith("requirements_")
        or name == "requirements.in"
    ):
        return ManifestFormat.REQUIREMENTS

    raise CLIError(
        "could not infer manifest type from "
        f"'{path.name}'; use --type "
        "requirements or --type pyproject"
    )


def _analysis_exit_code(
    severity: CheckSeverity,
    *,
    strict: bool,
) -> int:
    if severity is CheckSeverity.PASS:
        return 0

    if severity is CheckSeverity.WARN:
        return 1 if strict else 0

    if severity is CheckSeverity.FAIL:
        return 1

    return 2


def _comparison_exit_code(
    outcome: ComparisonOutcome,
) -> int:
    if outcome in {
        ComparisonOutcome.UNCHANGED,
        ComparisonOutcome.IMPROVEMENT,
    }:
        return 0

    if outcome in {
        ComparisonOutcome.REGRESSION,
        ComparisonOutcome.MIXED,
    }:
        return 1

    return 2


def _print_check_result(
    result: PackageCheckResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        print(result.model_dump_json(indent=2))
        return

    print(f"Requirement: {result.requirement}")

    print(f"Target:      {_format_target(result.target)}")

    print(f"Result:      {result.severity.value.upper()} ({result.status.value})")

    if result.selected_version:
        print(f"Version:     {result.selected_version}")

    if result.artifact is not None:
        print(f"Artifact:    {result.artifact.filename}")

    print(f"Summary:     {result.summary}")

    _print_notes(result.notes)


def _print_audit_result(
    result: ManifestAuditResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        print(result.model_dump_json(indent=2))
        return

    print(f"Target:            {_format_target(result.target)}")

    print(f"Overall:           {result.severity.value.upper()}")

    print(f"Manifest:          {result.manifest_format.value}")

    print(f"Manifest complete: {_yes_no(result.manifest_complete)}")

    if result.project_name:
        print(f"Project:           {result.project_name}")

    print(f"Requirements:      {result.requirements_found}")

    print(f"Unique checks:     {result.unique_checks}")

    print(
        "Package results:   "
        f"{result.counts.passed} pass, "
        f"{result.counts.warnings} warn, "
        f"{result.counts.failures} fail, "
        f"{result.counts.unknown} unknown"
    )

    print(
        "Manifest issues:   "
        f"{result.counts.manifest_warnings} warning, "
        f"{result.counts.manifest_errors} error"
    )

    print(f"Project Python:    {result.project_python.status.value}")

    if result.project_python.specifier:
        print(f"Requires-Python:  {result.project_python.specifier}")

    print()

    if result.issues:
        print("Manifest issues:")

        for issue in result.issues:
            _print_manifest_issue(issue)

        print()

    if result.findings:
        print("Findings:")

        for finding in result.findings:
            _print_finding(
                finding.requirement,
                finding.check,
            )

        print()

    print(result.summary)


def _print_comparison_result(
    result: TargetComparisonResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        print(result.model_dump_json(indent=2))
        return

    print(f"From:              {_format_target(result.from_target)}")

    print(f"To:                {_format_target(result.to_target)}")

    print(f"Outcome:           {result.outcome.value.upper()}")

    print(f"Manifest complete: {_yes_no(result.manifest_complete)}")

    print(f"Requirements:      {result.requirements_found}")

    print(
        "Compatibility:     "
        f"{result.counts.improvements} improved, "
        f"{result.counts.regressions} regressed, "
        f"{result.counts.unchanged} unchanged, "
        f"{result.counts.indeterminate} indeterminate"
    )

    print(
        "Operational:       "
        f"{result.counts.selected_version_changes} version, "
        f"{result.counts.artifact_changes} artifact, "
        f"{result.counts.applicability_changes} applicability "
        "change(s)"
    )

    print(
        "Project Python:    "
        f"{result.project_python.from_check.status.value} "
        "-> "
        f"{result.project_python.to_check.status.value} "
        f"({result.project_python.impact.value})"
    )

    print()

    if result.issues:
        print("Manifest issues:")

        for issue in result.issues:
            _print_manifest_issue(issue)

        print()

    if result.comparisons:
        print("Changes:")

        for comparison in result.comparisons:
            print(f"- {comparison.requirement.text}")

            print(f"  Impact: {comparison.impact.value}")

            print(
                "  Status: "
                f"{comparison.from_check.status.value} "
                "-> "
                f"{comparison.to_check.status.value}"
            )

            if comparison.selected_version_changed:
                print(
                    "  Version: "
                    f"{comparison.from_check.selected_version or '-'} "
                    "-> "
                    f"{comparison.to_check.selected_version or '-'}"
                )

            if comparison.artifact_changed:
                print(
                    "  Artifact: "
                    f"{_artifact_name(comparison.from_check)} "
                    "-> "
                    f"{_artifact_name(comparison.to_check)}"
                )

            if comparison.applicability_changed:
                print("  Applicability changed")

        print()

    print(result.summary)


def _print_finding(
    requirement: ManifestRequirement,
    check: PackageCheckResult,
) -> None:
    source = _format_requirement_source(requirement)

    print(f"- [{check.severity.value.upper()}] {requirement.text}")

    print(f"  Source: {source}")

    print(f"  Status: {check.status.value}")

    if check.selected_version:
        print(f"  Version: {check.selected_version}")

    if check.artifact is not None:
        print(f"  Artifact: {check.artifact.filename}")

    print(f"  {check.summary}")

    for note in check.notes:
        print(f"  Note: {note}")


def _print_manifest_issue(
    issue: ManifestIssue,
) -> None:
    source = issue.source

    if issue.line_start is not None:
        source = _format_line_range(
            issue.line_start,
            issue.line_end,
        )

    print(f"- [{issue.severity.value.upper()}] {issue.code.value}: {issue.message}")

    print(f"  Source: {source}")

    if issue.value is not None:
        print(f"  Value: {issue.value}")


def _print_notes(
    notes: Sequence[str],
) -> None:
    for note in notes:
        print(f"Note:        {note}")


def _format_target(
    target: TargetEnvironment,
) -> str:
    return f"CPython {target.python_version} / {target.platform}"


def _format_requirement_source(
    requirement: ManifestRequirement,
) -> str:
    if requirement.line_start is None:
        return requirement.source

    return _format_line_range(
        requirement.line_start,
        requirement.line_end,
    )


def _format_line_range(
    line_start: int,
    line_end: int | None,
) -> str:
    if line_end is None or line_end == line_start:
        return f"line {line_start}"

    return f"lines {line_start}-{line_end}"


def _artifact_name(
    result: PackageCheckResult,
) -> str:
    if result.artifact is None:
        return "-"

    return result.artifact.filename


def _yes_no(
    value: bool,
) -> str:
    return "yes" if value else "no"
