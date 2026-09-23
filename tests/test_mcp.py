import sys

import pytest
from mcp import (
    Client,
    StdioServerParameters,
)
from mcp.types import TextContent

import compatag.mcp_server as mcp_server
from compatag.distributions import (
    DistributionFile,
    DistributionKind,
    ProjectDistributions,
)


def _wheel(
    name: str,
    *,
    version: str = "1.0",
    tag: str = "py3-none-any",
) -> DistributionFile:
    filename = f"{name}-{version}-{tag}.whl"

    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.WHEEL,
        hashes={"sha256": f"digest-{filename}"},
    )


def _sdist(
    name: str,
    *,
    version: str = "1.0",
) -> DistributionFile:
    filename = f"{name}-{version}.tar.gz"

    return DistributionFile(
        filename=filename,
        url=f"https://example.test/{filename}",
        version=version,
        kind=DistributionKind.SDIST,
        hashes={"sha256": f"digest-{filename}"},
    )


def _project(
    name: str,
    files: tuple[
        DistributionFile,
        ...,
    ],
) -> ProjectDistributions:
    versions = tuple(sorted({file.version for file in files if file.version is not None}))

    return ProjectDistributions(
        name=name,
        api_version="1.4",
        versions=versions,
        files=files,
    )


class FakePyPIClient:
    def __init__(
        self,
        projects: dict[
            str,
            ProjectDistributions,
        ],
    ) -> None:
        self.projects = projects
        self.requests: list[str] = []

        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(
        self,
    ) -> "FakePyPIClient":
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.exit_count += 1

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        self.requests.append(name)

        return self.projects[name]


def _install_fake_client(
    monkeypatch,
    fake_client: FakePyPIClient,
) -> None:
    monkeypatch.setattr(
        mcp_server,
        "PyPIClient",
        lambda: fake_client,
    )


def _text_content(
    result,
) -> str:
    return "\n".join(
        block.text
        for block in result.content
        if isinstance(
            block,
            TextContent,
        )
    )


@pytest.mark.asyncio
async def test_server_exposes_exactly_three_tools(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient({})

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        response = await client.list_tools()

    tools = {tool.name: tool for tool in response.tools}

    assert set(tools) == {
        "check_package",
        "audit_manifest",
        "compare_targets",
    }

    for tool in tools.values():
        assert tool.annotations is not None

        assert tool.annotations.read_only_hint is True

        assert tool.annotations.open_world_hint is True

        assert tool.output_schema is not None

    check_tool = tools["check_package"]

    properties = check_tool.input_schema["properties"]

    assert "requirement" in properties
    assert "target" in properties
    assert "ctx" not in properties


@pytest.mark.asyncio
async def test_check_package_returns_structured_output(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "check_package",
            {
                "requirement": "demo>=1",
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

    assert not result.is_error
    assert result.structured_content is not None

    assert result.structured_content["severity"] == "pass"

    assert result.structured_content["status"] == "universal_wheel_available"


@pytest.mark.asyncio
async def test_audit_manifest_returns_structured_output(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "audit_manifest",
            {
                "manifest_text": "demo\n",
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
                "verbosity": "all",
            },
        )

    assert not result.is_error
    assert result.structured_content is not None

    assert result.structured_content["severity"] == "pass"

    assert result.structured_content["requirements_found"] == 1


@pytest.mark.asyncio
async def test_compare_targets_reports_regression(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient(
        {
            "demo": _project(
                "demo",
                (
                    _wheel(
                        "demo",
                        tag=("cp311-cp311-win_amd64"),
                    ),
                    _sdist("demo"),
                ),
            ),
        }
    )

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "compare_targets",
            {
                "manifest_text": "demo\n",
                "from_target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
                "to_target": {
                    "python_version": "3.11",
                    "platform": ("manylinux_2_17_x86_64"),
                },
            },
        )

    assert not result.is_error
    assert result.structured_content is not None

    assert result.structured_content["outcome"] == "regression"


@pytest.mark.asyncio
async def test_requirements_manifest_rejects_extras(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient({})

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "audit_manifest",
            {
                "manifest_text": "demo\n",
                "manifest_type": ("requirements"),
                "extras": ["dev"],
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

    assert result.is_error

    assert "extras can only be selected" in _text_content(result)

    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_invalid_concurrency_is_rejected_by_tool_schema(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient({})

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "audit_manifest",
            {
                "manifest_text": "demo\n",
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
                "max_concurrency": 0,
            },
        )

    assert result.is_error
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_lifespan_reuses_one_project_source(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        first = await client.call_tool(
            "check_package",
            {
                "requirement": "demo>=1",
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

        second = await client.call_tool(
            "check_package",
            {
                "requirement": "demo<2",
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

        assert not first.is_error
        assert not second.is_error

        assert fake_client.enter_count == 1
        assert fake_client.exit_count == 0

    assert fake_client.exit_count == 1


@pytest.mark.asyncio
async def test_compare_reuses_project_lookup_within_call(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient(
        {
            "demo": _project(
                "demo",
                (_wheel("demo"),),
            ),
        }
    )

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "compare_targets",
            {
                "manifest_text": ("demo>=1\ndemo<2\n"),
                "from_target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
                "to_target": {
                    "python_version": "3.11",
                    "platform": ("manylinux_2_17_x86_64"),
                },
                "verbosity": "all",
            },
        )

    assert not result.is_error

    assert fake_client.requests == ["demo"]


@pytest.mark.asyncio
async def test_manifest_requirement_limit_is_enforced(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient({})

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    manifest_text = "".join(f"demo-{index}\n" for index in range(101))

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "audit_manifest",
            {
                "manifest_text": manifest_text,
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

    assert result.is_error

    assert "tool limit is 100" in _text_content(result)

    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_manifest_byte_limit_is_enforced(
    monkeypatch,
) -> None:
    fake_client = FakePyPIClient({})

    _install_fake_client(
        monkeypatch,
        fake_client,
    )

    manifest_text = "# " + ("é" * 70_000)

    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(
            "audit_manifest",
            {
                "manifest_text": manifest_text,
                "target": {
                    "python_version": "3.11",
                    "platform": "win_amd64",
                },
            },
        )

    assert result.is_error
    assert fake_client.requests == []


@pytest.mark.asyncio
async def test_stdio_subprocess_discovers_tools() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "compatag.mcp_server",
        ],
    )

    async with Client(
        server,
        read_timeout_seconds=10.0,
    ) as client:
        response = await client.list_tools()

    assert {tool.name for tool in response.tools} == {
        "check_package",
        "audit_manifest",
        "compare_targets",
    }
