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
    parser = subparsers.add_parser("remove", help="Remove a volume for a service")
    parser.add_argument(
        "service_name",
        help="Name of the service to remove volume for",
        nargs="?",
        default=None,
    )
    parser.add_argument("volume", help="Name of the volume to remove")
    parser.set_defaults(func=remove)


def remove(args: Namespace) -> None:
    """Remove a volume for a service."""
    service_name = args.service_name
    volume = args.volume
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    with Status(
        f"Removing {volume} volume for {service.name}", f"{volume} removed"
    ) as status:
        try:
            run_docker_compose_command(f"-f {service_config_file_path} rm {volume} -v")
        except DockerComposeError as dce:
            status.print(
                f"Failed to remove {volume} volume for {service.name}: {dce.stderr}"
            )
            exit(1)
