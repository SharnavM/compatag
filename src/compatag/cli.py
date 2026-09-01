from argparse import ArgumentParser
from collections.abc import Sequence
from importlib.metadata import version


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="compatag",
        description="Preflight Python package compatibility across deployment targets.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('compatag')}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not vars(args):
        parser.print_help()

    return 0
