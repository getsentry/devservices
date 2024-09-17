from __future__ import annotations

import os
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from exceptions import DockerComposeError
from utils.console import Status
from utils.docker_compose import run_docker_compose_command
from utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("stop", help="Stop a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to stop", nargs="?", default=None
    )
    parser.set_defaults(func=stop)


def stop(args: Namespace) -> None:
    """Stop a service and its dependencies."""
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_stop = "default"
    mode_dependencies = " ".join(modes[mode_to_stop])
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    with Status(f"Stopping {service.name}", f"{service.name} stopped") as status:
        try:
            run_docker_compose_command(
                f"-f {service_config_file_path} down {mode_dependencies}"
            )
        except DockerComposeError as dce:
            status.print(f"Failed to stop {service.name}: {dce.stderr}")
            exit(1)
