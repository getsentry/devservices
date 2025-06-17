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
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import MAX_LOG_LINES
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorError
from devservices.utils.console import Console
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import State
from devservices.utils.state import StateTables
from devservices.utils.supervisor import SupervisorManager


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
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices logs sentry`) or run the command from a directory with a devservices configuration."
        )
        exit(1)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)
    state = State()

    modes = service.config.modes
    starting_modes = set(
        state.get_active_modes_for_service(service.name, StateTables.STARTING_SERVICES)
    )
    started_modes = set(
        state.get_active_modes_for_service(service.name, StateTables.STARTED_SERVICES)
    )
    active_modes = starting_modes.union(started_modes)
    mode_dependencies = set()
    for active_mode in active_modes:
        active_mode_dependencies = modes.get(active_mode, [])
        mode_dependencies.update(active_mode_dependencies)

    # If no active modes found but service is running, fall back to default mode
    if not mode_dependencies and "default" in modes:
        mode_dependencies.update(modes["default"])

    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    running_services = starting_services.union(started_services)
    if service.name not in running_services:
        console.warning(f"Service {service.name} is not running")
        return

    try:
        remote_dependencies = install_and_verify_dependencies(
            service, modes=list(active_modes)
        )
    except DependencyError as de:
        capture_exception(de)
        console.failure(
            f"{str(de)}. If this error persists, try running `devservices purge`"
        )
        exit(1)
    try:
        logs_output = _logs(service, remote_dependencies, list(mode_dependencies))
    except DockerComposeError as dce:
        capture_exception(dce, level="info")
        console.failure(f"Failed to get logs for {service.name}: {dce.stderr}")
        exit(1)
    for log in logs_output:
        log_stdout: str | None = log.stdout
        if log_stdout is not None:
            console.info(log_stdout)

    # Get supervisor program logs
    supervisor_programs = [
        dep
        for dep in mode_dependencies
        if dep in service.config.dependencies
        and service.config.dependencies[dep].dependency_type
        == DependencyType.SUPERVISOR
    ]

    if len(supervisor_programs) > 0:
        supervisor_logs = _supervisor_logs(service, supervisor_programs)
        for program_name, log_content in supervisor_logs.items():
            if log_content:
                console.info(f"=== Logs for supervisor program: {program_name} ===")
                console.info(log_content)


def _logs(
    service: Service,
    remote_dependencies: set[InstalledRemoteDependency],
    mode_dependencies: list[str],
) -> list[subprocess.CompletedProcess[str]]:
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
        command="logs",
        options=["-n", MAX_LOG_LINES],
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    cmd_outputs = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(run_cmd, cmd.full_command, current_env)
            for cmd in docker_compose_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            cmd_outputs.append(future.result())

    return cmd_outputs


def _supervisor_logs(
    service: Service, supervisor_programs: list[str]
) -> dict[str, str]:
    if not supervisor_programs:
        return {}

    supervisor_logs: dict[str, str] = {}

    config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    try:
        manager = SupervisorManager(service.name, config_file_path)
    except SupervisorConfigError as e:
        capture_exception(e)
        return supervisor_logs

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(get_program_logs_with_error_handling, manager, program_name)
            for program_name in supervisor_programs
        ]
        for future in concurrent.futures.as_completed(futures):
            program_name, log_content = future.result()
            supervisor_logs[program_name] = log_content

    return supervisor_logs


def get_program_logs_with_error_handling(
    manager: SupervisorManager, program_name: str
) -> tuple[str, str]:
    try:
        log_content = manager.get_program_logs(program_name)
        return program_name, log_content
    except SupervisorError as e:
        capture_exception(e)
        return program_name, f"Error getting logs for {program_name}: {str(e)}"
