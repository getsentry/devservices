from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.exceptions import DockerComposeError
from devservices.utils.console import Status
from devservices.utils.docker_compose import run_docker_compose_command
from devservices.utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("start", help="Start a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to start", nargs="?", default=None
    )
    parser.set_defaults(func=start)


def start(args: Namespace) -> None:
    """Start a service and its dependencies."""
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)

    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_start = "default"
    mode_dependencies = " ".join(modes[mode_to_start])

    with Status(f"Starting {service.name}", f"{service.name} started") as status:
        try:
            run_docker_compose_command(
                service, f"up -d {mode_dependencies}", force_update_dependencies=True
            )
        except DockerComposeError as dce:
            status.print(f"Failed to start {service.name}: {dce.stderr}")
            exit(1)
