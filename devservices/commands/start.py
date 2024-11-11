from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.docker_compose import run_docker_compose_command
from devservices.utils.services import find_matching_service
from devservices.utils.state import State


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("start", help="Start a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to start", nargs="?", default=None
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.set_defaults(func=start)


def start(args: Namespace) -> None:
    """Start a service and its dependencies."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        console.failure(str(e))
        exit(1)

    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_start = "default"
    mode_dependencies = modes[mode_to_start]

    with Status(
        lambda: console.warning(f"Starting {service.name}"),
        lambda: console.success(f"{service.name} started"),
    ) as status:
        try:
            remote_dependencies = install_and_verify_dependencies(
                service, force_update_dependencies=True
            )
        except DependencyError as de:
            status.failure(str(de))
            exit(1)
        try:
            run_docker_compose_command(
                service,
                "up",
                mode_dependencies,
                remote_dependencies,
                options=["-d"],
            )
        except DockerComposeError as dce:
            status.failure(f"Failed to start {service.name}: {dce.stderr}")
            exit(1)
    # TODO: We should factor in healthchecks here before marking service as running
    state = State()
    state.add_started_service(service.name, mode_to_start)
