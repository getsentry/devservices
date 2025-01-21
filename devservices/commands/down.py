from __future__ import annotations

import concurrent.futures
import os
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import State
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "down", help="Bring down a service and its dependencies"
    )
    parser.add_argument(
        "service_name",
        help="Name of the service to bring down",
        nargs="?",
        default=None,
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.set_defaults(func=down)


def down(args: Namespace) -> None:
    """Bring down a service and its dependencies."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e)
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices down sentry`) or run the command from a directory with a devservices configuration."
        )
        exit(1)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)

    modes = service.config.modes

    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    if service.name not in active_services:
        console.warning(f"{service.name} is not running")
        exit(0)

    active_starting_modes = state.get_active_modes_for_service(
        service.name, StateTables.STARTING_SERVICES
    )
    active_started_modes = state.get_active_modes_for_service(
        service.name, StateTables.STARTED_SERVICES
    )
    active_modes = active_starting_modes or active_started_modes
    mode_dependencies = set()
    for active_mode in active_modes:
        active_mode_dependencies = modes.get(active_mode, [])
        mode_dependencies.update(active_mode_dependencies)

    with Status(
        lambda: console.warning(f"Stopping {service.name}"),
    ) as status:
        try:
            remote_dependencies = install_and_verify_dependencies(
                service, modes=active_modes
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)
        try:
            remote_dependencies = get_non_shared_remote_dependencies(
                service, remote_dependencies
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)

        # Check if any service depends on the service we are trying to bring down
        # TODO: We should also take into account the active modes of the other services (this is not trivial to do)
        other_started_services = active_services.difference({service.name})
        dependent_service_name = None
        for other_started_service in other_started_services:
            other_service = find_matching_service(other_started_service)
            other_service_active_starting_modes = state.get_active_modes_for_service(
                other_service.name, StateTables.STARTING_SERVICES
            )
            other_service_active_started_modes = state.get_active_modes_for_service(
                other_service.name, StateTables.STARTED_SERVICES
            )
            other_service_active_modes = (
                other_service_active_starting_modes
                or other_service_active_started_modes
            )
            dependency_graph = construct_dependency_graph(
                other_service, other_service_active_modes
            )
            # If the service we are trying to bring down is in the dependency graph of another service, we should not bring it down
            if service.name in dependency_graph.graph:
                dependent_service_name = other_started_service
                break

        # If no other service depends on the service we are trying to bring down, we can bring it down
        if dependent_service_name is None:
            try:
                _down(service, remote_dependencies, list(mode_dependencies), status)
            except DockerComposeError as dce:
                capture_exception(dce)
                status.failure(f"Failed to stop {service.name}: {dce.stderr}")
                exit(1)
        else:
            status.warning(
                f"Leaving {service.name} running because it is being used by {dependent_service_name}"
            )

    # TODO: We should factor in healthchecks here before marking service as not running
    state.remove_service_entry(service.name, StateTables.STARTING_SERVICES)
    state.remove_service_entry(service.name, StateTables.STARTED_SERVICES)
    if dependent_service_name is None:
        console.success(f"{service.name} stopped")


def _bring_down_dependency(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> subprocess.CompletedProcess[str]:
    # TODO: Get rid of these constants, we need a smarter way to determine the containers being brought down
    for dependency in cmd.services:
        status.info(f"Stopping {dependency}")
    return run_cmd(cmd.full_command, current_env)


def _down(
    service: Service,
    remote_dependencies: set[InstalledRemoteDependency],
    mode_dependencies: list[str],
    status: Status,
) -> None:
    relative_local_dependency_directory = os.path.relpath(
        os.path.join(DEVSERVICES_DEPENDENCIES_CACHE_DIR, DEPENDENCY_CONFIG_VERSION),
        service.repo_path,
    )
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    # Set the environment variable for the local dependencies directory to be used by docker compose
    current_env = os.environ.copy()
    current_env[
        DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
    ] = relative_local_dependency_directory
    docker_compose_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=list(remote_dependencies),
        current_env=current_env,
        command="stop",
        options=[],
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    cmd_outputs = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(_bring_down_dependency, cmd, current_env, status)
            for cmd in docker_compose_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            cmd_outputs.append(future.result())
