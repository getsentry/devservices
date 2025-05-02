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
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import DependencyType
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
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
    parser.add_argument(
        "--exclude-local",
        help="Exclude dependencies with local runtime from being brought down",
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
        capture_exception(e, level="info")
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
    exclude_local = args.exclude_local

    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    if service.name not in active_services:
        console.warning(f"{service.name} is not running")
        return  # Since exit(0) is captured as an internal_error by sentry

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
                service, remote_dependencies, exclude_local
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
        services_with_local_runtimes = state.get_services_by_runtime(
            ServiceRuntime.LOCAL
        )
        dependent_service_name = None
        # We can ignore checking if anything relies on the service
        # if it is a locally running service
        if service.name not in services_with_local_runtimes:
            dependent_service_name = _get_dependent_service(
                service, other_started_services, state
            )

        # If no other service depends on the service we are trying to bring down, we can bring it down
        if dependent_service_name is None:
            try:
                bring_down_service(
                    service,
                    remote_dependencies,
                    list(mode_dependencies),
                    exclude_local,
                    status,
                )
            except DockerComposeError as dce:
                capture_exception(dce, level="info")
                status.failure(f"Failed to stop {service.name}: {dce.stderr}")
                exit(1)
        else:
            status.warning(
                f"Leaving {service.name} running because it is being used by {dependent_service_name}"
            )

    # TODO: We should factor in healthchecks here before marking service as not running
    state.remove_service_entry(service.name, StateTables.STARTING_SERVICES)
    state.remove_service_entry(service.name, StateTables.STARTED_SERVICES)

    dependencies_with_local_runtimes = set()
    for service_with_local_runtime in services_with_local_runtimes:
        if service_with_local_runtime in {
            dep.service_name for dep in remote_dependencies
        }:
            dependencies_with_local_runtimes.add(service_with_local_runtime)

    active_dependencies_with_local_runtimes = set()
    for dependency_with_local_runtime in dependencies_with_local_runtimes:
        if dependency_with_local_runtime in active_services:
            active_dependencies_with_local_runtimes.add(dependency_with_local_runtime)

    if not exclude_local and len(active_dependencies_with_local_runtimes) > 0:
        status.warning("Stopping dependencies with local runtimes...")
        for local_dependency in active_dependencies_with_local_runtimes:
            down(Namespace(service_name=local_dependency, exclude_local=exclude_local))

    if dependent_service_name is None:
        console.success(f"{service.name} stopped")


def bring_down_service(
    service: Service,
    remote_dependencies: set[InstalledRemoteDependency],
    mode_dependencies: list[str],
    exclude_local: bool,
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
    state = State()

    # We want to ignore any dependencies that are set to run locally if we are excluding local dependencies
    services_with_local_runtimes = state.get_services_by_runtime(ServiceRuntime.LOCAL)

    dependencies_with_local_runtimes = set()
    for service_with_local_runtime in services_with_local_runtimes:
        if service_with_local_runtime in {
            dep.service_name for dep in remote_dependencies
        }:
            dependencies_with_local_runtimes.add(service_with_local_runtime)

    docker_compose_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=[
            dep
            for dep in remote_dependencies
            if dep.service_name not in dependencies_with_local_runtimes
        ],
        current_env=current_env,
        command="stop",
        options=[],
        service_config_file_path=service_config_file_path,
        mode_dependencies=[
            dep
            for dep in mode_dependencies
            if dep not in dependencies_with_local_runtimes
        ],
    )

    cmd_outputs = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(_bring_down_dependency, cmd, current_env, status)
            for cmd in docker_compose_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            cmd_outputs.append(future.result())


def _get_dependent_service(
    service: Service,
    other_started_services: set[str],
    state: State,
) -> str | None:
    for other_started_service in other_started_services:
        other_service = find_matching_service(other_started_service)
        other_service_active_starting_modes = state.get_active_modes_for_service(
            other_service.name, StateTables.STARTING_SERVICES
        )
        other_service_active_started_modes = state.get_active_modes_for_service(
            other_service.name, StateTables.STARTED_SERVICES
        )
        other_service_active_modes = (
            other_service_active_starting_modes or other_service_active_started_modes
        )
        dependency_graph = construct_dependency_graph(
            other_service, other_service_active_modes
        )
        # If the service we are trying to bring down is in the dependency graph of another service,
        # we should not bring it down
        if (
            DependencyNode(name=service.name, dependency_type=DependencyType.SERVICE)
            in dependency_graph.graph
        ):
            return other_started_service

    return None


def _bring_down_dependency(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> subprocess.CompletedProcess[str]:
    # TODO: Get rid of these constants, we need a smarter way to determine the containers being brought down
    for dependency in cmd.services:
        status.info(f"Stopping {dependency}")
    return run_cmd(cmd.full_command, current_env)
