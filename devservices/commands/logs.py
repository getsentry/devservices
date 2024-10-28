from __future__ import annotations

import sys
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.exceptions import DockerComposeError
from devservices.utils.docker_compose import run_docker_compose_command
from devservices.utils.services import find_matching_service


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
    mode_dependencies = modes[mode_to_use]

    try:
        logs = run_docker_compose_command(service, "logs", mode_dependencies)
    except DockerComposeError as dce:
        print(f"Failed to get logs for {service.name}: {dce.stderr}")
        exit(1)
    for log in logs:
        sys.stdout.write(log.stdout)
        sys.stdout.flush()
