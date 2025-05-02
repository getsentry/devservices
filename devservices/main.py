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
from sentry_sdk import set_context
from sentry_sdk import set_tag
from sentry_sdk import set_user
from sentry_sdk import start_transaction
from sentry_sdk.integrations.argv import ArgvIntegration
from sentry_sdk.types import Event
from sentry_sdk.types import Hint

from devservices.commands import down
from devservices.commands import list_dependencies
from devservices.commands import list_services
from devservices.commands import logs
from devservices.commands import purge
from devservices.commands import serve
from devservices.commands import status
from devservices.commands import toggle
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

error_trace_ids = set()


def before_send_error(event: Event, hint: Hint) -> Event:
    """Gets the trace_id from the errors we care about.

    This function is used as a before_send callback for Sentry to track error trace IDs.
    It adds the trace_id to error_trace_ids set for non-info level events.
    """
    if event["level"] != "info":
        error_trace_ids.add(event["contexts"]["trace"]["trace_id"])
    return event


def before_send_transaction(event: Event, hint: Hint) -> Event:
    """Manually sets the status of a transaction.

    This function is used as a before_send_transaction callback for Sentry to mark transaction status
    as unknown if they don't correspond to errors we care about.
    """
    if event["contexts"]["trace"]["trace_id"] not in error_trace_ids:
        event["contexts"]["trace"]["status"] = "unknown"
    return event


if not disable_sentry:
    init(
        dsn="https://56470da7302c16e83141f62f88e46449@o1.ingest.us.sentry.io/4507946704961536",
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        enable_tracing=True,
        integrations=[ArgvIntegration()],
        environment=sentry_environment,
        before_send=before_send_error,
        before_send_transaction=before_send_transaction,
        release=current_version,
    )
    username = getpass.getuser()
    set_user({"username": username})
    set_tag("user_platform", platform.platform())
    if sentry_environment == "CI":
        set_context(
            "github",
            {
                "github_action": os.environ.get("GITHUB_ACTION"),
                "github_action_path": os.environ.get("GITHUB_ACTION_PATH"),
                "github_repository": os.environ.get("GITHUB_REPOSITORY"),
                "github_ref_name": os.environ.get("GITHUB_REF_NAME"),
                "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                "github_url": f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}",
                "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "github_workflow": os.environ.get("GITHUB_WORKFLOW"),
                "github_workflow_run_id": os.environ.get("GITHUB_WORKFLOW_RUN_ID"),
                "github_sha": os.environ.get("GITHUB_SHA"),
            },
        )
    try:
        git_version = get_git_version()
        set_tag("git_version", git_version)
    except GitError as e:
        capture_exception(e, level="info")
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
        capture_exception(e, level="info")
        console.failure(str(e))
        exit(1)
    except DockerComposeInstallationError as e:
        capture_exception(e, level="info")
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
    serve.add_parser(subparsers)
    toggle.add_parser(subparsers)

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
