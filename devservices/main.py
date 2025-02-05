from __future__ import annotations

import argparse
import atexit
import getpass
import logging
import os
import platform
from importlib import metadata

from sentry_sdk import capture_exception
from sentry_sdk import flush
from sentry_sdk import init
from sentry_sdk import set_tag
from sentry_sdk import set_user
from sentry_sdk import start_transaction
from sentry_sdk.integrations.argv import ArgvIntegration

from devservices.commands import down
from devservices.commands import list_dependencies
from devservices.commands import list_services
from devservices.commands import logs
from devservices.commands import purge
from devservices.commands import status
from devservices.commands import up
from devservices.commands import update
from devservices.constants import LOGGER_NAME
from devservices.exceptions import DockerComposeInstallationError
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import GitError
from devservices.utils.console import Console
from devservices.utils.docker_compose import check_docker_compose_version
from devservices.utils.git import get_git_version

sentry_environment = (
    "development" if os.environ.get("IS_DEV", default="0") == "1" else "production"
)
if os.environ.get("CI", default="false") == "true":
    sentry_environment = "CI"

disable_sentry = os.environ.get("DEVSERVICES_DISABLE_SENTRY", default="0") == "1"
logging.basicConfig(level=logging.INFO)
current_version = metadata.version("devservices")

if not disable_sentry:
    init(
        dsn="https://56470da7302c16e83141f62f88e46449@o1.ingest.us.sentry.io/4507946704961536",
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        enable_tracing=True,
        integrations=[ArgvIntegration()],
        environment=sentry_environment,
        release=current_version,
    )
    username = getpass.getuser()
    set_user({"username": username})
    set_tag("user_platform", platform.platform())
    try:
        git_version = get_git_version()
        set_tag("git_version", git_version)
    except GitError as e:
        capture_exception(e)
        logging.debug("Failed to get git version: %s", e)
        set_tag("git_version", "unknown")


@atexit.register
def cleanup() -> None:
    flush()


def main() -> None:
    console = Console()
    set_tag("devservices_version", current_version)
    try:
        check_docker_compose_version()
    except DockerDaemonNotRunningError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except DockerComposeInstallationError as e:
        capture_exception(e)
        console.failure("Failed to ensure docker compose is installed and up-to-date")
        exit(1)
    parser = argparse.ArgumentParser(
        prog="devservices",
        description="CLI tool for managing service dependencies.",
        usage="devservices [-h] [--version] COMMAND ...",
    )
    parser.add_argument("--version", action="version", version=current_version)

    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="")

    # Add subparsers for each command
    up.add_parser(subparsers)
    down.add_parser(subparsers)
    list_dependencies.add_parser(subparsers)
    list_services.add_parser(subparsers)
    status.add_parser(subparsers)
    logs.add_parser(subparsers)
    update.add_parser(subparsers)
    purge.add_parser(subparsers)

    args = parser.parse_args()

    # If the command has a debug flag, set the logger to debug
    if "debug" in args and args.debug:
        logger = logging.getLogger(LOGGER_NAME)
        logger.setLevel(logging.DEBUG)

    if args.command:
        # Call the appropriate function based on the command
        with start_transaction(op="command", name=args.command):
            args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
