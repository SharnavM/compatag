from compatag.cli import main


def test_cli_without_arguments_shows_help(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage: compatag" in captured.out
    assert "Preflight Python package compatibility" in captured.out
