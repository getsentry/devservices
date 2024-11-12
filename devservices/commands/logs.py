from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.constants import MAX_LOG_LINES
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.utils.console import Console
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.docker_compose import run_docker_compose_command
from devservices.utils.services import find_matching_service
from devservices.utils.state import State


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
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        console.failure(str(e))
        exit(1)

    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_use = "default"
    mode_dependencies = modes[mode_to_use]

    state = State()
    running_services = state.get_started_services()
    if service.name not in running_services:
        console.warning(f"Service {service.name} is not running")
        return

    try:
        remote_dependencies = install_and_verify_dependencies(service)
    except DependencyError as de:
        console.failure(str(de))
        exit(1)
    try:
        logs_output = run_docker_compose_command(
            service,
            "logs",
            mode_dependencies,
            remote_dependencies,
            options=["-n", MAX_LOG_LINES],
        )
    except DockerComposeError as dce:
        console.failure(f"Failed to get logs for {service.name}: {dce.stderr}")
        exit(1)
    for log in logs_output:
        log_stdout: str | None = log.stdout
        if log_stdout is not None:
            console.info(log_stdout)
