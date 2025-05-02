from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.commands.down import down
from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import DependencyType
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import get_volumes_for_containers
from devservices.utils.docker import remove_docker_resources
from devservices.utils.docker import stop_containers
from devservices.utils.services import find_matching_service
from devservices.utils.state import State
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("reset", help="Reset a service's volumes")
    parser.add_argument(
        "service_name",
        help="Name of the service to reset volumes for",
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=reset)


def reset(args: Namespace) -> None:
    """Reset a specified service's volumes."""
    console = Console()
    service_name = args.service_name

    try:
        matching_containers = get_matching_containers(
            [
                DEVSERVICES_ORCHESTRATOR_LABEL,
                f"com.docker.compose.service={args.service_name}",
            ]
        )
    except DockerDaemonNotRunningError as e:
        console.warning(str(e))
        return
    except DockerError as e:
        console.failure(f"Failed to get matching containers {e.stderr}")
        exit(1)

    if len(matching_containers) == 0:
        console.failure(f"No containers found for {service_name}")
        exit(1)

    try:
        matching_volumes = get_volumes_for_containers(matching_containers)
    except DockerError as e:
        console.failure(f"Failed to get matching volumes {e.stderr}")
        exit(1)

    if len(matching_volumes) == 0:
        console.failure(f"No volumes found for {service_name}")
        exit(1)

    state = State()
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    active_service_names = starting_services.union(started_services)

    # TODO: We should add threading here to speed up the process
    for active_service_name in active_service_names:
        active_service = find_matching_service(active_service_name)
        starting_active_modes = state.get_active_modes_for_service(
            active_service_name, StateTables.STARTING_SERVICES
        )
        started_active_modes = state.get_active_modes_for_service(
            active_service_name, StateTables.STARTED_SERVICES
        )
        active_modes = starting_active_modes or started_active_modes
        dependency_graph = construct_dependency_graph(active_service, active_modes)
        if (
            DependencyNode(name=service_name, dependency_type=DependencyType.COMPOSE)
            in dependency_graph.graph
        ):
            console.warning(
                f"Bringing down {active_service_name} in order to safely reset {service_name}"
            )
            down(Namespace(service_name=active_service_name, exclude_local=True))

    with Status(
        lambda: console.warning(f"Resetting docker volumes for {service_name}"),
        lambda: console.success(f"Docker volumes have been reset for {service_name}"),
    ):
        try:
            stop_containers(matching_containers, should_remove=True)
        except DockerError as e:
            console.failure(
                f"Failed to stop and remove {', '.join(matching_containers)}\nError: {e.stderr}"
            )
            capture_exception(e)
            exit(1)
        try:
            remove_docker_resources("volume", list(matching_volumes))
        except DockerError as e:
            console.failure(
                f"Failed to remove volumes {', '.join(matching_volumes)}\nError: {e.stderr}"
            )
            capture_exception(e)
            exit(1)
