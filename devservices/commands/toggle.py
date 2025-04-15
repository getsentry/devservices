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
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("toggle", help="Toggle how a service is run")
    parser.add_argument(
        "service_name", help="Name of the service to toggle", nargs="?", default=None
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "runtime",
        help="Runtime to use for the service",
        choices=["containerized", "local"],
        nargs="?",
        default="containerized",
    )
    parser.set_defaults(func=toggle)


def toggle(args: Namespace) -> None:
    """Toggle how a service is run."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices toggle snuba`) or run the command from a directory with a devservices configuration."
        )
        exit(1)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)

    desired_runtime = args.runtime
    state = State()
    current_runtime = state.get_service_runtime(service.name)
    if current_runtime.value == desired_runtime:
        console.warning(
            f"{service.name} is already running in {desired_runtime} runtime"
        )
        return
    if desired_runtime == "local":
        starting_services = set(
            state.get_service_entries(StateTables.STARTING_SERVICES)
        )
        started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
        active_services = starting_services.union(started_services)
        if service.name in active_services:
            # TODO: This is a stupid case, we shouldn't care since it's already technically running locally
            console.warning(f"{service.name} is running, please stop it first")
            return

        # TODO: Clean up naming of active_service vs service (can be confusing)
        for active_service_name in active_services:
            active_service = find_matching_service(active_service_name)
            starting_active_modes = set(
                state.get_active_modes_for_service(
                    active_service_name, StateTables.STARTING_SERVICES
                )
            )
            started_active_modes = set(
                state.get_active_modes_for_service(
                    active_service_name, StateTables.STARTED_SERVICES
                )
            )
            active_modes = starting_active_modes.union(started_active_modes)
            dependency_graph = construct_dependency_graph(
                active_service, list(active_modes)
            )
            if service.name in [node.name for node in dependency_graph.graph]:
                # TODO: We should bring down for every mode it is currently running in
                service_dependency_config = active_service.config.dependencies.get(
                    service.name, None
                )
                if (
                    service_dependency_config is None
                    or service_dependency_config.remote is None
                ):
                    # TODO: This shouldn't happen?
                    console.warning(
                        f"{service.name} is not a remote dependency of {active_service_name}"
                    )
                    continue
                service_mode = service_dependency_config.remote.mode
                _bring_down_containerized_service(
                    service,
                    [service_mode],
                )
                break
        state.update_service_runtime(service.name, ServiceRuntime(desired_runtime))
    elif desired_runtime == "containerized":
        starting_services = set(
            state.get_service_entries(StateTables.STARTING_SERVICES)
        )
        started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
        active_services = starting_services.union(started_services)
        if service.name in active_services:
            console.warning(f"{service.name} is running, please stop it first")
            return
        dependent_services = []
        for active_service_name in active_services:
            active_service = find_matching_service(active_service_name)
            starting_active_modes = set(
                state.get_active_modes_for_service(
                    active_service_name, StateTables.STARTING_SERVICES
                )
            )
            started_active_modes = set(
                state.get_active_modes_for_service(
                    active_service_name, StateTables.STARTED_SERVICES
                )
            )
            active_modes = starting_active_modes.union(started_active_modes)
            dependency_graph = construct_dependency_graph(
                active_service, list(active_modes)
            )
            dependent_services.extend(
                [
                    node.name
                    for node in dependency_graph.graph
                    if node.name == active_service_name
                ]
            )
        if len(dependent_services) > 0:
            them_or_it = "them" if len(dependent_services) > 1 else "it"
            console.warning(
                f"{service.name} is a dependency of {', '.join(dependent_services)}, please stop {them_or_it} first"
            )
            return
        state.update_service_runtime(service.name, ServiceRuntime(desired_runtime))
    console.success(f"{service.name} is now running in {desired_runtime} runtime")


def _bring_down_containerized_service(
    service: Service,
    active_modes: list[str],
) -> None:
    """Bring down a containerized service running within another service."""
    console = Console()
    with Status(
        lambda: console.warning(f"Stopping {service.name}"),
    ) as status:
        mode_dependencies = set()
        for active_mode in active_modes:
            active_mode_dependencies = service.config.modes.get(active_mode, [])
            mode_dependencies.update(active_mode_dependencies)
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
        try:
            _down(service, remote_dependencies, list(mode_dependencies), status)
        except DockerComposeError as dce:
            capture_exception(dce, level="info")
            status.failure(f"Failed to stop {service.name}: {dce.stderr}")
            exit(1)


# TODO: This is duplicate code with the down command, we should refactor this
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
    state = State()
    locally_running_services = state.get_services_by_runtime(ServiceRuntime.LOCAL)
    mode_dependencies = [
        dep for dep in mode_dependencies if dep not in locally_running_services
    ]
    remote_dependencies = {
        dep
        for dep in remote_dependencies
        if dep.service_name not in locally_running_services
    }
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


# TODO: This is duplicate code with the down command, we should refactor this
def _bring_down_dependency(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> subprocess.CompletedProcess[str]:
    for dependency in cmd.services:
        status.info(f"Stopping {dependency}")
    return run_cmd(cmd.full_command, current_env)
