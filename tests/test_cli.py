import json

import compatag.cli as cli
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

    async def __aenter__(
        self,
    ) -> "FakePyPIClient":
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        return None

    async def get_project(
        self,
        name: str,
    ) -> ProjectDistributions:
        self.requests.append(name)
        return self.projects[name]


def _install_fake_client(
    monkeypatch,
    client: FakePyPIClient,
) -> None:
    monkeypatch.setattr(
        cli,
        "PyPIClient",
        lambda: client,
    )


def test_cli_without_arguments_shows_help(
    capsys,
) -> None:
    exit_code = cli.main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage: compatag" in captured.out

    assert "check" in captured.out
    assert "audit" in captured.out
    assert "compare" in captured.out
    assert "mcp" in captured.out


def test_check_json_returns_structured_result(
    monkeypatch,
    capsys,
) -> None:
    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (_wheel("demo"),),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "check",
        "demo>=1",
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
        "--json",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0

    assert payload["package"] == "demo"
    assert payload["severity"] == "pass"

    assert payload["status"] == "universal_wheel_available"


def test_check_warning_is_zero_by_default(
    monkeypatch,
    capsys,
) -> None:
    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (_sdist("demo"),),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "check",
        "demo",
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "WARN" in captured.out

    assert "source_build_required" in captured.out


def test_check_warning_is_one_in_strict_mode(
    monkeypatch,
    capsys,
) -> None:
    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (_sdist("demo"),),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "check",
        "demo",
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
        "--strict",
    ])

    capsys.readouterr()

    assert exit_code == 1


def test_invalid_target_returns_two(
    capsys,
) -> None:
    exit_code = cli.main([
        "check",
        "demo",
        "--python",
        "3.11.9",
        "--platform",
        "win_amd64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 2

    assert "python_version" in captured.err


def test_audit_auto_detects_requirements_file(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    manifest = tmp_path / "requirements.txt"

    manifest.write_text(
        "alpha\nbeta\n",
        encoding="utf-8",
    )

    client = FakePyPIClient({
        "alpha": _project(
            "alpha",
            (_wheel("alpha"),),
        ),
        "beta": _project(
            "beta",
            (_wheel("beta"),),
        ),
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "audit",
        str(manifest),
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
        "--json",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0

    assert payload["manifest_format"] == "requirements"

    assert payload["requirements_found"] == 2


def test_audit_extra_is_rejected_for_requirements(
    tmp_path,
    capsys,
) -> None:
    manifest = tmp_path / "requirements.txt"

    manifest.write_text(
        "demo\n",
        encoding="utf-8",
    )

    exit_code = cli.main([
        "audit",
        str(manifest),
        "--extra",
        "dev",
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 2

    assert "--extra is only valid" in captured.err


def test_manifest_type_override_handles_custom_filename(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    manifest = tmp_path / "dependencies.list"

    manifest.write_text(
        "demo\n",
        encoding="utf-8",
    )

    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (_wheel("demo"),),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "audit",
        str(manifest),
        "--type",
        "requirements",
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
        "--json",
    ])

    captured = capsys.readouterr()

    assert exit_code == 0

    payload = json.loads(captured.out)

    assert payload["manifest_format"] == "requirements"


def test_unknown_manifest_name_requires_type(
    tmp_path,
    capsys,
) -> None:
    manifest = tmp_path / "dependencies.list"

    manifest.write_text(
        "demo\n",
        encoding="utf-8",
    )

    exit_code = cli.main([
        "audit",
        str(manifest),
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 2

    assert "could not infer manifest type" in captured.err


def test_compare_regression_returns_one(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    manifest = tmp_path / "requirements.txt"

    manifest.write_text(
        "demo\n",
        encoding="utf-8",
    )

    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (
                _wheel(
                    "demo",
                    tag=("cp311-cp311-win_amd64"),
                ),
                _sdist("demo"),
            ),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "compare",
        str(manifest),
        "--from-python",
        "3.11",
        "--from-platform",
        "win_amd64",
        "--to-python",
        "3.11",
        "--to-platform",
        ("manylinux_2_17_x86_64"),
        "--json",
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1

    assert payload["outcome"] == "regression"


def test_compare_unchanged_returns_zero(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    manifest = tmp_path / "requirements.txt"

    manifest.write_text(
        "demo\n",
        encoding="utf-8",
    )

    client = FakePyPIClient({
        "demo": _project(
            "demo",
            (_wheel("demo"),),
        )
    })

    _install_fake_client(
        monkeypatch,
        client,
    )

    exit_code = cli.main([
        "compare",
        str(manifest),
        "--from-python",
        "3.11",
        "--from-platform",
        "win_amd64",
        "--to-python",
        "3.11",
        "--to-platform",
        "manylinux_2_17_x86_64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "UNCHANGED" in captured.out


def test_missing_manifest_returns_two(
    tmp_path,
    capsys,
) -> None:
    missing = tmp_path / "requirements.txt"

    exit_code = cli.main([
        "audit",
        str(missing),
        "--python",
        "3.11",
        "--platform",
        "win_amd64",
    ])

    captured = capsys.readouterr()

    assert exit_code == 2

    assert "could not read" in captured.err
