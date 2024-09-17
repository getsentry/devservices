from __future__ import annotations

import argparse
import atexit

import sentry_sdk
from sentry_sdk.integrations.argv import ArgvIntegration

from devservices.commands import list_dependencies
from devservices.commands import list_services
from devservices.commands import logs
from devservices.commands import start
from devservices.commands import status
from devservices.commands import stop

sentry_sdk.init(
    dsn="https://56470da7302c16e83141f62f88e46449@o1.ingest.us.sentry.io/4507946704961536",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    enable_tracing=True,
    integrations=[ArgvIntegration()],
)


@atexit.register
def cleanup() -> None:
    sentry_sdk.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DevServices CLI tool for managing Docker Compose services."
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.0.1")

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
        with sentry_sdk.start_transaction(op="command", name=args.command):
            args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
