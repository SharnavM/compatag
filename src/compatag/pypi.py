from __future__ import annotations

import re
import warnings
from datetime import datetime
from importlib.metadata import version as distribution_version
from types import TracebackType
from typing import Self
from urllib.parse import urljoin

import httpx
from packaging.utils import (
    InvalidName,
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from compatag.distributions import (
    DistributionFile,
    DistributionKind,
    ProjectDistributions,
)

_PYPI_SIMPLE_ROOT = "https://pypi.org/simple/"
_SIMPLE_JSON_MEDIA_TYPE = "application/vnd.pypi.simple.v1+json"

_SUPPORTED_API_MAJOR = 1
_SUPPORTED_API_MINOR = 4

_API_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)$")

_REQUEST_TIMEOUT = httpx.Timeout(
    15.0,
    connect=5.0,
)


class PyPIError(RuntimeError):
    """Base exception for PyPI lookup failures."""


class InvalidProjectNameError(PyPIError):
    """The supplied project name is not a valid Python distribution name."""


class ProjectNotFoundError(PyPIError):
    """The requested project does not exist on PyPI."""


class PyPIRequestError(PyPIError):
    """PyPI could not be reached or returned an unsuccessful status."""


class PyPIResponseError(PyPIError):
    """PyPI returned data Compatag could not safely interpret."""


class SimpleAPIVersionWarning(UserWarning):
    """PyPI advertises a newer compatible minor Simple API version."""


class _SimpleMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_version: str = Field(
        default="1.0",
        alias="api-version",
    )


class _SimpleProjectStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "active"
    reason: str | None = None


class _SimpleFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filename: str
    url: str
    hashes: dict[str, str]

    requires_python: str | None = Field(
        default=None,
        alias="requires-python",
    )

    yanked: bool | str = False

    size: int | None = None

    upload_time: datetime | None = Field(
        default=None,
        alias="upload-time",
    )


class _SimpleProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    meta: _SimpleMeta
    files: list[_SimpleFile]

    versions: list[str] = Field(default_factory=list)

    project_status: _SimpleProjectStatus | None = Field(
        default=None,
        alias="project-status",
    )


class PyPIClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http_client = http_client is None

        self._http_client = http_client or httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        normalized_name = _normalize_project_name(name)

        project_url = f"{_PYPI_SIMPLE_ROOT}{normalized_name}/"

        try:
            response = await self._http_client.get(
                project_url,
                headers=_request_headers(),
            )
        except httpx.RequestError as exc:
            raise PyPIRequestError(
                f"failed to query PyPI for project '{normalized_name}': {exc}"
            ) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProjectNotFoundError(f"project '{normalized_name}' was not found on PyPI")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PyPIRequestError(
                f"PyPI returned HTTP {response.status_code} for project '{normalized_name}'"
            ) from exc

        _require_simple_json(response)

        try:
            payload = _SimpleProject.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise PyPIResponseError(
                f"PyPI returned invalid project data for '{normalized_name}'"
            ) from exc

        _check_api_version(payload.meta.api_version)

        _check_response_name(
            payload.name,
            normalized_name,
        )

        return _build_project(
            payload,
            response,
        )


def _normalize_project_name(name: str) -> str:
    candidate = name.strip()

    try:
        return str(
            canonicalize_name(
                candidate,
                validate=True,
            )
        )
    except InvalidName as exc:
        raise InvalidProjectNameError(f"invalid Python project name: {name!r}") from exc


def _request_headers() -> dict[str, str]:
    return {
        "Accept": _SIMPLE_JSON_MEDIA_TYPE,
        "User-Agent": (
            f"compatag/{distribution_version('compatag')} (+https://github.com/SharnavM/compatag)"
        ),
    }


def _require_simple_json(
    response: httpx.Response,
) -> None:
    content_type = response.headers.get(
        "content-type",
        "",
    )

    media_type = content_type.partition(";")[0].strip().lower()

    if media_type != _SIMPLE_JSON_MEDIA_TYPE:
        raise PyPIResponseError(
            f"PyPI returned an unexpected content type: {content_type or '<missing>'}"
        )


def _check_api_version(
    api_version: str,
) -> None:
    match = _API_VERSION_PATTERN.fullmatch(api_version)

    if match is None:
        raise PyPIResponseError(f"PyPI returned an invalid Simple API version '{api_version}'")

    major = int(match.group("major"))
    minor = int(match.group("minor"))

    if major != _SUPPORTED_API_MAJOR:
        raise PyPIResponseError(
            "unsupported Simple API major "
            f"version {major}; Compatag supports "
            f"major version {_SUPPORTED_API_MAJOR}"
        )

    if minor > _SUPPORTED_API_MINOR:
        warnings.warn(
            (
                "PyPI advertises Simple API "
                f"{api_version}, newer than "
                "Compatag's tested "
                f"1.{_SUPPORTED_API_MINOR} support"
            ),
            SimpleAPIVersionWarning,
            stacklevel=3,
        )


def _check_response_name(
    response_name: str,
    expected_name: str,
) -> None:
    try:
        normalized_response_name = str(
            canonicalize_name(
                response_name,
                validate=True,
            )
        )
    except InvalidName as exc:
        raise PyPIResponseError(f"PyPI returned an invalid project name '{response_name}'") from exc

    if normalized_response_name != expected_name:
        raise PyPIResponseError(
            f"PyPI returned project '{response_name}' while '{expected_name}' was requested"
        )


def _build_project(
    payload: _SimpleProject,
    response: httpx.Response,
) -> ProjectDistributions:
    project_name = str(canonicalize_name(payload.name))

    files = tuple(
        sorted(
            (
                _build_distribution_file(
                    file,
                    project_name,
                    response,
                )
                for file in payload.files
            ),
            key=lambda file: file.filename.lower(),
        )
    )

    status = payload.project_status or _SimpleProjectStatus()

    return ProjectDistributions(
        name=project_name,
        api_version=payload.meta.api_version,
        versions=tuple(sorted(payload.versions)),
        files=files,
        status=status.status,
        status_reason=status.reason,
    )


def _build_distribution_file(
    file: _SimpleFile,
    project_name: str,
    response: httpx.Response,
) -> DistributionFile:
    kind, version, parse_error = _parse_distribution_filename(
        file.filename,
        project_name,
    )

    if isinstance(file.yanked, str):
        yanked = True
        yanked_reason = file.yanked or None
    else:
        yanked = file.yanked
        yanked_reason = None

    hashes = {algorithm.lower(): digest for algorithm, digest in sorted(file.hashes.items())}

    return DistributionFile(
        filename=file.filename,
        url=urljoin(
            str(response.request.url),
            file.url,
        ),
        version=version,
        kind=kind,
        hashes=hashes,
        requires_python=file.requires_python,
        yanked=yanked,
        yanked_reason=yanked_reason,
        size=file.size,
        upload_time=file.upload_time,
        parse_error=parse_error,
    )


def _parse_distribution_filename(
    filename: str,
    expected_name: str,
) -> tuple[
    DistributionKind,
    str | None,
    str | None,
]:
    if filename.endswith(".whl"):
        try:
            (
                project_name,
                version,
                _,
                _,
            ) = parse_wheel_filename(filename)
        except InvalidWheelFilename as exc:
            return (
                DistributionKind.UNKNOWN,
                None,
                str(exc),
            )

        if project_name != expected_name:
            return (
                DistributionKind.UNKNOWN,
                str(version),
                (f"filename belongs to project '{project_name}', not '{expected_name}'"),
            )

        return (
            DistributionKind.WHEEL,
            str(version),
            None,
        )

    if filename.endswith((".tar.gz", ".zip")):
        try:
            project_name, version = parse_sdist_filename(filename)
        except InvalidSdistFilename as exc:
            return (
                DistributionKind.UNKNOWN,
                None,
                str(exc),
            )

        if project_name != expected_name:
            return (
                DistributionKind.UNKNOWN,
                str(version),
                (f"filename belongs to project '{project_name}', not '{expected_name}'"),
            )

        return (
            DistributionKind.SDIST,
            str(version),
            None,
        )

    return (
        DistributionKind.UNKNOWN,
        None,
        "unsupported distribution filename",
    )
