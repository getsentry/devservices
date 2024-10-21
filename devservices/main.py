from __future__ import annotations

import argparse
import atexit
import os
from importlib import metadata

import sentry_sdk
from sentry_sdk.integrations.argv import ArgvIntegration

from devservices.commands import list_dependencies
from devservices.commands import list_services
from devservices.commands import logs
from devservices.commands import start
from devservices.commands import status
from devservices.commands import stop
from devservices.commands import update
from devservices.commands.check_for_update import check_for_update
from devservices.utils.docker_compose import check_docker_compose_version

sentry_environment = (
    "development" if os.environ.get("IS_DEV", default=False) else "production"
)

disable_sentry = os.environ.get("DISABLE_SENTRY", default=False)

if not disable_sentry:
    sentry_sdk.init(
        dsn="https://56470da7302c16e83141f62f88e46449@o1.ingest.us.sentry.io/4507946704961536",
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        enable_tracing=True,
        integrations=[ArgvIntegration()],
        environment=sentry_environment,
    )


@atexit.register
def cleanup() -> None:
    sentry_sdk.flush()


def main() -> None:
    check_docker_compose_version()
    parser = argparse.ArgumentParser(
        prog="devservices",
        description="CLI tool for managing service dependencies.",
        usage="devservices [-h] [--version] COMMAND ...",
    )
    parser.add_argument(
        "--version", action="version", version=metadata.version("devservices")
    )

    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="")

    # Add subparsers for each command
    start.add_parser(subparsers)
    stop.add_parser(subparsers)
    list_dependencies.add_parser(subparsers)
    list_services.add_parser(subparsers)
    status.add_parser(subparsers)
    logs.add_parser(subparsers)
    update.add_parser(subparsers)

    args = parser.parse_args()

    if args.command:
        # Call the appropriate function based on the command
        with sentry_sdk.start_transaction(op="command", name=args.command):
            args.func(args)
    else:
        parser.print_help()

    if args.command != "update":
        newest_version = check_for_update(metadata.version("devservices"))
        if newest_version != metadata.version("devservices"):
            print(
                f"\n\033[93mWARNING: A new version of devservices is available: {newest_version}\033[0m"
            )
            print("To update, run: \033[1mdevservices update\033[0m")


if __name__ == "__main__":
    main()
