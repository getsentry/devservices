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
from devservices.constants import DOCKER_COMPOSE_COMMAND_LENGTH
from devservices.exceptions import ConfigError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ModeDoesNotExistError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import State


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
    except (ConfigError, ServiceNotFoundError) as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)

    modes = service.config.modes
    mode = args.mode

    state = State()
    started_services = state.get_started_services()
    running_mode = state.get_mode_for_service(service.name) or "default"

    # TODO: Remove this once we properly handle mode switching
    if service.name in started_services and running_mode != mode:
        console.warning(
            f"Service '{service.name}' is already running in mode: '{running_mode}', restarting in mode: '{mode}'"
        )
        with Status() as status:
            try:
                remote_dependencies = install_and_verify_dependencies(
                    service, mode=running_mode
                )
            except DependencyError as de:
                capture_exception(de)
                status.failure(str(de))
                exit(1)
            except ModeDoesNotExistError as mde:
                capture_exception(mde)
                status.failure(str(mde))
                exit(1)
            service_config_file_path = os.path.join(
                service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            )
            current_env = os.environ.copy()
            running_mode_dependencies = modes[running_mode]
            remote_dependencies_to_bring_down = get_non_shared_remote_dependencies(
                service, remote_dependencies
            )
            down_docker_compose_commands = get_docker_compose_commands_to_run(
                service=service,
                remote_dependencies=list(remote_dependencies_to_bring_down),
                current_env=current_env,
                command="down",
                options=[],
                service_config_file_path=service_config_file_path,
                mode_dependencies=running_mode_dependencies,
            )

            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(run_cmd, cmd, current_env)
                    for cmd in down_docker_compose_commands
                ]
                for future in concurrent.futures.as_completed(futures):
                    future.result()

            state.remove_started_service(service.name)

    with Status(
        lambda: console.warning(f"Starting '{service.name}' in mode: '{mode}'"),
        lambda: console.success(f"{service.name} started"),
    ) as status:
        try:
            status.info("Retrieving dependencies")
            remote_dependencies = install_and_verify_dependencies(
                service, force_update_dependencies=True, mode=mode
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(str(de))
            exit(1)
        except ModeDoesNotExistError as mde:
            status.failure(str(mde))
            exit(1)
        try:
            _create_devservices_network()
        except subprocess.CalledProcessError:
            # Network already exists, ignore the error
            pass
        try:
            mode_dependencies = modes[mode]
            _up(service, remote_dependencies, mode_dependencies, status)
        except DockerComposeError as dce:
            capture_exception(dce)
            status.failure(f"Failed to start {service.name}: {dce.stderr}")
            exit(1)
    # TODO: We should factor in healthchecks here before marking service as running
    state = State()
    state.add_started_service(service.name, mode)


def _bring_up_dependency(
    cmd: list[str], current_env: dict[str, str], status: Status, len_options: int
) -> subprocess.CompletedProcess[str]:
    # TODO: Get rid of these constants, we need a smarter way to determine the containers being brought up
    for dependency in cmd[DOCKER_COMPOSE_COMMAND_LENGTH:-len_options]:
        status.info(f"Starting {dependency}")
    return run_cmd(cmd, current_env)


def _up(
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
    options = ["-d"]
    dependency_graph = construct_dependency_graph(service)
    starting_order = dependency_graph.get_starting_order()
    sorted_remote_dependencies = sorted(
        remote_dependencies, key=lambda dep: starting_order.index(dep.service_name)
    )
    docker_compose_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=sorted_remote_dependencies,
        current_env=current_env,
        command="up",
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    for cmd in docker_compose_commands:
        _bring_up_dependency(cmd, current_env, status, len(options))


def _create_devservices_network() -> None:
    subprocess.run(
        ["docker", "network", "create", "devservices"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
