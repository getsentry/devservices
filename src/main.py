from __future__ import annotations

import argparse

from commands import list_dependencies
from commands import list_services
from commands import logs
from commands import start
from commands import status
from commands import stop


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DevServices CLI tool for managing Docker Compose services."
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add subparsers for each command
    start.add_parser(subparsers)
    stop.add_parser(subparsers)
    list_dependencies.add_parser(subparsers)
    list_services.add_parser(subparsers)
    status.add_parser(subparsers)
    logs.add_parser(subparsers)

    args = parser.parse_args()

    if args.command:
        # Call the appropriate function based on the command
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
