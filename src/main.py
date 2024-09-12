from __future__ import annotations

import argparse

import sentry_sdk
from commands import list_dependencies
from commands import list_services
from commands import logs
from commands import start
from commands import status
from commands import stop
from sentry_sdk.integrations.argv import ArgvIntegration


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

    # Set up Sentry
    sentry_sdk.init(
        dsn="https://e9f6505edbde9a6b4528b7f56ce0c508@o1383316.ingest.us.sentry.io/4507942331875328",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
        # Enable performance monitoring
        enable_tracing=True,
        # Enable the Argv integration
        integrations=[ArgvIntegration()],
    )

    if args.command:
        # Call the appropriate function based on the command
        with sentry_sdk.start_transaction(op="command", name=args.command):
            args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
