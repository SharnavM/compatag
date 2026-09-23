import asyncio

import httpx
import pytest

import compatag.pypi as pypi_module
from compatag.distributions import (
    DistributionKind,
)
from compatag.pypi import (
    InvalidProjectNameError,
    ProjectNotFoundError,
    PyPIClient,
    PyPIRequestError,
    PyPIResponseError,
    SimpleAPIVersionWarning,
)

_SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"


class _OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"x" * 40
        yield b"y" * 40


def _project_payload() -> dict[str, object]:
    return {
        "meta": {
            "api-version": "1.4",
            "_last-serial": 12345,
            "future-meta-field": "ignored",
        },
        "name": "demo-project",
        "versions": [
            "2.0",
            "1.0",
        ],
        "project-status": {
            "status": "deprecated",
            "reason": ("Use demo-project-next instead."),
        },
        "files": [
            {
                "filename": ("demo_project-1.0.tar.gz"),
                "url": ("https://files.pythonhosted.org/demo_project-1.0.tar.gz"),
                "hashes": {"sha256": "sdist-digest"},
                "requires-python": ">=3.9",
                "yanked": "Broken metadata",
                "size": 2048,
            },
            {
                "filename": ("demo_project-1.0-py3-none-any.whl"),
                "url": ("../../packages/demo_project-1.0-py3-none-any.whl"),
                "hashes": {"SHA256": "wheel-digest"},
                "requires-python": ">=3.9",
                "yanked": False,
                "size": 1024,
                "upload-time": ("2026-08-30T12:34:56Z"),
                "core-metadata": {"sha256": "metadata-digest"},
                "provenance": ("https://example.test/provenance"),
                "future-file-field": True,
            },
        ],
        "future-top-level-field": {"ignored": True},
    }


def _json_response(
    payload: dict[str, object],
    *,
    status_code: int = 200,
    content_type: str = _SIMPLE_JSON,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers={"Content-Type": content_type},
    )


@pytest.mark.asyncio
async def test_get_project_normalizes_name_and_parses_distributions() -> None:
    requests: list[httpx.Request] = []

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)

        return _json_response(_project_payload())

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        project = await client.get_project(" Demo_Project ")

    assert len(requests) == 1

    request = requests[0]

    assert str(request.url) == ("https://pypi.org/simple/demo-project/")

    assert request.headers["Accept"] == _SIMPLE_JSON

    assert request.headers["User-Agent"].startswith("compatag/")

    assert project.name == "demo-project"
    assert project.api_version == "1.4"

    assert project.versions == (
        "1.0",
        "2.0",
    )

    assert project.status == "deprecated"

    assert project.status_reason == ("Use demo-project-next instead.")

    files = {file.filename: file for file in project.files}

    wheel = files["demo_project-1.0-py3-none-any.whl"]

    assert wheel.kind is DistributionKind.WHEEL

    assert wheel.version == "1.0"

    assert wheel.url == ("https://pypi.org/packages/demo_project-1.0-py3-none-any.whl")

    assert wheel.hashes == {"sha256": "wheel-digest"}

    assert wheel.requires_python == ">=3.9"
    assert wheel.yanked is False
    assert wheel.yanked_reason is None
    assert wheel.size == 1024

    assert wheel.upload_time is not None
    assert wheel.parse_error is None

    sdist = files["demo_project-1.0.tar.gz"]

    assert sdist.kind is DistributionKind.SDIST

    assert sdist.version == "1.0"
    assert sdist.yanked is True

    assert sdist.yanked_reason == ("Broken metadata")


@pytest.mark.asyncio
async def test_project_defaults_to_active_when_status_is_omitted() -> None:
    payload = _project_payload()

    payload.pop("project-status")

    transport = httpx.MockTransport(lambda request: _json_response(payload))

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        project = await client.get_project("demo-project")

    assert project.status == "active"
    assert project.status_reason is None


@pytest.mark.asyncio
async def test_unknown_legacy_distribution_is_preserved() -> None:
    payload = _project_payload()

    payload["files"] = [
        {
            "filename": ("demo_project-0.8-py3.11.egg"),
            "url": ("https://files.pythonhosted.org/demo_project-0.8-py3.11.egg"),
            "hashes": {"sha256": "legacy-digest"},
            "yanked": False,
            "size": 500,
        }
    ]

    transport = httpx.MockTransport(lambda request: _json_response(payload))

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        project = await client.get_project("demo-project")

    legacy_file = project.files[0]

    assert legacy_file.kind is DistributionKind.UNKNOWN

    assert legacy_file.version is None

    assert legacy_file.parse_error == ("unsupported distribution filename")


@pytest.mark.asyncio
async def test_invalid_project_name_is_rejected_before_network_request() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        raise AssertionError("network request should not be made")

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(InvalidProjectNameError):
            await client.get_project("not a valid project name!")


@pytest.mark.asyncio
async def test_missing_project_raises_project_not_found() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            404,
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            ProjectNotFoundError,
            match="missing-project",
        ):
            await client.get_project("missing-project")


@pytest.mark.asyncio
async def test_server_error_raises_request_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            503,
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIRequestError,
            match="HTTP 503",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_transport_failure_raises_request_error() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        raise httpx.ConnectError(
            "connection failed",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIRequestError,
            match="failed to query PyPI",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_non_simple_json_response_is_rejected() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html></html>",
            headers={"Content-Type": "text/html"},
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIResponseError,
            match="unexpected content type",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_invalid_json_response_is_rejected() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": _SIMPLE_JSON},
            request=request,
        )
    )

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIResponseError,
            match="invalid project data",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_newer_api_major_version_is_rejected() -> None:
    payload = _project_payload()

    payload["meta"] = {"api-version": "2.0"}

    transport = httpx.MockTransport(lambda request: _json_response(payload))

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIResponseError,
            match="major version 2",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_newer_api_minor_version_warns_but_remains_usable() -> None:
    payload = _project_payload()

    payload["meta"] = {"api-version": "1.5"}

    transport = httpx.MockTransport(lambda request: _json_response(payload))

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.warns(
            SimpleAPIVersionWarning,
            match="1.5",
        ):
            project = await client.get_project("demo-project")

    assert project.api_version == "1.5"


@pytest.mark.asyncio
async def test_mismatched_response_project_is_rejected() -> None:
    payload = _project_payload()

    payload["name"] = "different-project"

    transport = httpx.MockTransport(lambda request: _json_response(payload))

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        with pytest.raises(
            PyPIResponseError,
            match=("while 'demo-project' was requested"),
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_repeated_project_lookup_uses_cache() -> None:
    request_count = 0

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal request_count
        request_count += 1

        return _json_response(_project_payload())

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        first = await client.get_project("demo-project")

        second = await client.get_project("demo-project")

    assert request_count == 1
    assert first == second


@pytest.mark.asyncio
async def test_concurrent_project_lookup_is_coalesced() -> None:
    request_count = 0

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal request_count
        request_count += 1

        return _json_response(_project_payload())

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(http_client=http_client)

        first, second = await asyncio.gather(
            client.get_project("demo-project"),
            client.get_project("demo-project"),
        )

    assert request_count == 1
    assert first == second


@pytest.mark.asyncio
async def test_project_cache_expires(
    monkeypatch,
) -> None:
    request_count = 0
    now = [1000.0]

    monkeypatch.setattr(
        pypi_module.time,
        "monotonic",
        lambda: now[0],
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal request_count
        request_count += 1

        return _json_response(_project_payload())

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(
            http_client=http_client,
            cache_ttl_seconds=10.0,
        )

        await client.get_project("demo-project")

        now[0] += 11.0

        await client.get_project("demo-project")

    assert request_count == 2


@pytest.mark.asyncio
async def test_declared_oversized_response_is_rejected() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{}",
            headers={
                "Content-Type": _SIMPLE_JSON,
                "Content-Length": "1000",
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(
            http_client=http_client,
            max_response_bytes=64,
        )

        with pytest.raises(
            PyPIResponseError,
            match="response limit",
        ):
            await client.get_project("demo-project")


@pytest.mark.asyncio
async def test_streamed_oversized_response_is_rejected() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": _SIMPLE_JSON,
            },
            stream=_OversizedStream(),
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = PyPIClient(
            http_client=http_client,
            max_response_bytes=64,
        )

        with pytest.raises(
            PyPIResponseError,
            match="response limit",
        ):
            await client.get_project("demo-project")
