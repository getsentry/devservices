from __future__ import annotations

import os
import pty
import shlex
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import SupervisorConfigError
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
        console.failure(
            f"{str(e)}. Please run the command from a directory with a valid devservices configuration."
        )
        return
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)

    config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )

    try:
        manager = SupervisorManager(service.name, config_file_path)
    except SupervisorConfigError as e:
        capture_exception(e, level="info")
        console.failure(
            f"Unable to bring up devserver due to supervisor config error: {str(e)}"
        )
        return

    if not manager.has_programs:
        console.failure(
            "No programs found in config. Please add the devserver in the `x-programs` block to your config.yml"
        )
        return

    try:
        devserver_command = manager.get_program_command("devserver")
    except SupervisorConfigError as e:
        capture_exception(e, level="info")
        console.failure(f"Error when getting devserver command: {str(e)}")
        return

    argv = shlex.split(devserver_command) + args.extra
    pty.spawn(argv)
