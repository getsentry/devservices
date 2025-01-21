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
from devservices.exceptions import ContainerHealthcheckFailedError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ModeDoesNotExistError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker import check_all_containers_healthy
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.docker_compose import get_container_names_for_project
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import State
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("up", help="Bring up a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to bring up", nargs="?", default=None
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--mode",
        help="Mode to use for the service",
        default="default",
    )
    parser.set_defaults(func=up)


def up(args: Namespace) -> None:
    """Bring up a service and its dependencies."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e)
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices up sentry`) or run the command from a directory with a devservices configuration."
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
    mode = args.mode

    state = State()

    with Status(
        lambda: console.warning(f"Starting '{service.name}' in mode: '{mode}'"),
        lambda: console.success(f"{service.name} started"),
    ) as status:
        try:
            status.info("Retrieving dependencies")
            remote_dependencies = install_and_verify_dependencies(
                service, force_update_dependencies=True, modes=[mode]
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)
        except ModeDoesNotExistError as mde:
            status.failure(str(mde))
            exit(1)
        try:
            _create_devservices_network()
        except subprocess.CalledProcessError:
            # Network already exists, ignore the error
            pass
        # Add the service to the starting services table
        state.update_service_entry(service.name, mode, StateTables.STARTING_SERVICES)
        try:
            mode_dependencies = modes[mode]
            _up(service, [mode], remote_dependencies, mode_dependencies, status)
        except DockerComposeError as dce:
            capture_exception(dce)
            status.failure(f"Failed to start {service.name}: {dce.stderr}")
            exit(1)
    # TODO: We should factor in healthchecks here before marking service as running
    state.remove_service_entry(service.name, StateTables.STARTING_SERVICES)
    state.update_service_entry(service.name, mode, StateTables.STARTED_SERVICES)


def _bring_up_dependency(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> subprocess.CompletedProcess[str]:
    for dependency in cmd.services:
        status.info(f"Starting {dependency}")
    return run_cmd(cmd.full_command, current_env)


def _up(
    service: Service,
    modes: list[str],
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
    dependency_graph = construct_dependency_graph(service, modes=modes)
    starting_order = dependency_graph.get_starting_order()
    sorted_remote_dependencies = sorted(
        remote_dependencies, key=lambda dep: starting_order.index(dep.service_name)
    )
    docker_compose_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=sorted_remote_dependencies,
        current_env=current_env,
        command="up",
        options=["-d", "--pull", "always"],
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    containers_to_check = []
    with concurrent.futures.ThreadPoolExecutor() as dependency_executor:
        futures = [
            dependency_executor.submit(_bring_up_dependency, cmd, current_env, status)
            for cmd in docker_compose_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            _ = future.result()

    for cmd in docker_compose_commands:
        try:
            container_names = get_container_names_for_project(
                cmd.project_name, cmd.config_path
            )
            containers_to_check.extend(container_names)
        except DockerComposeError as dce:
            status.failure(
                f"Failed to get containers to healthcheck for {cmd.project_name}: {dce.stderr}"
            )
            exit(1)
    try:
        check_all_containers_healthy(status, containers_to_check)
    except ContainerHealthcheckFailedError as e:
        status.failure(str(e))
        exit(1)


def _create_devservices_network() -> None:
    subprocess.run(
        ["docker", "network", "create", "devservices"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
