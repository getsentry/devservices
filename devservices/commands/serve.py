from __future__ import annotations

import os
import pty
import shlex
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.utils.console import Console
from devservices.utils.services import find_matching_service
from devservices.utils.supervisor import SupervisorManager


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    # prefix_chars is a hack to allow all options to be passed through to the devserver without argparse complaining
    parser = subparsers.add_parser(
        "serve", help="Serve the devserver", prefix_chars="+"
    )
    parser.add_argument(
        "extra", nargs="*", help="Flags to pass through to the devserver"
    )
    parser.set_defaults(func=serve)


def serve(args: Namespace) -> None:
    """Serve the devserver."""
    console = Console()

    try:
        service = find_matching_service()
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices up sentry`) or run the command from a directory with a devservices configuration."
        )
        exit(1)

    manager = SupervisorManager(
        os.path.join(service.repo_path, f"{DEVSERVICES_DIR_NAME}/processes.conf"),
        service_name=service.name,
    )
    devserver_command = manager.get_program_command("devserver")
    argv = shlex.split(devserver_command) + args.extra
    pty.spawn(argv)
