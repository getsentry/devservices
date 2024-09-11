from __future__ import annotations

import os
import sys
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from exceptions import DockerComposeError
from utils.docker_compose import run_docker_compose_command
from utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("logs", help="View logs for a service")
    parser.add_argument(
        "service_name",
        help="Name of the service to view logs for",
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=logs)


def logs(args: Namespace) -> None:
    """View the logs for a specified service."""
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_use = "default"
    mode_dependencies = " ".join(modes[mode_to_use])
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    try:
        logs = run_docker_compose_command(
            f"-f {service_config_file_path} logs {mode_dependencies}"
        )
    except DockerComposeError as dce:
        print(f"Failed to get logs for {service.name}: {dce.stderr}")
        exit(1)
    sys.stdout.write(logs.stdout)
    sys.stdout.flush()
