from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace
from collections import namedtuple
from datetime import timedelta
from typing import TypedDict

from sentry_sdk import capture_exception

from devservices.constants import Color
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.exceptions import SupervisorConfigError
from devservices.utils.console import Console
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import DependencyGraph
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from devservices.utils.supervisor import ProcessInfo
from devservices.utils.supervisor import SupervisorManager

BASE_INDENTATION = "  "


ServiceStatus = namedtuple("ServiceStatus", ["name", "formatted_output"])


class ServiceStatusOutput(TypedDict):
    Service: str
    Name: str
    State: str
    Health: str
    RunningFor: str
    Publishers: list[Ports]


class Ports(TypedDict):
    URL: str
    PublishedPort: int
    TargetPort: int
    Protocol: str


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("status", help="View status of a service")
    parser.add_argument(
        "service_name",
        help="Name of the service to view status for",
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=status)


def status(args: Namespace) -> None:
    """Get the status of a specified service."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e)
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices status sentry`) or run the command from a directory with a devservices configuration."
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
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    if service.name not in active_services:
        console.warning(f"Status unavailable. {service.name} is not running standalone")
        return  # Since exit(0) is captured as an internal_error by sentry

    config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    process_statuses = {}

    try:
        supervisor_manager = SupervisorManager(service.name, config_file_path)
        process_statuses = supervisor_manager.get_all_process_info()
    except SupervisorConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)

    try:
        status_tree = get_status_for_service(service, process_statuses)
    except DependencyError as de:
        capture_exception(de)
        console.failure(
            f"{str(de)}. If this error persists, try running `devservices purge`"
        )
        exit(1)
    except DockerComposeError as dce:
        capture_exception(dce)
        console.failure(f"Failed to get status for {service.name}: {dce.stderr}")
        exit(1)
    console.info(status_tree)


def get_status_for_service(
    service: Service, process_statuses: dict[str, ProcessInfo]
) -> str:
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

    remote_dependencies = install_and_verify_dependencies(service)

    dependency_graph = construct_dependency_graph(service, list(active_modes))

    status_json_results = get_status_json_results(
        service, remote_dependencies, list(mode_dependencies)
    )

    docker_compose_service_to_status = parse_docker_compose_status(status_json_results)
    status_tree = generate_service_status_tree(
        service.name,
        process_statuses,
        dependency_graph,
        docker_compose_service_to_status,
    )
    return status_tree


def get_status_json_results(
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
        command="ps",
        options=["--format", "json"],
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


def generate_service_status_tree(
    service_name: str,
    process_statuses: dict[str, ProcessInfo],
    dependency_graph: DependencyGraph,
    docker_compose_service_to_status: dict[str, ServiceStatusOutput],
    indentation: str = "",
) -> str:
    output = []
    state = State()
    services_with_local_runtime = state.get_services_by_runtime(ServiceRuntime.LOCAL)

    dependencies = dependency_graph.graph[
        DependencyNode(name=service_name, dependency_type=DependencyType.SERVICE)
    ]

    # Using indentation == "" to check if the service is the root service (hacky, but works) since the root service may not be in the services_with_local_runtime set
    runtime = (
        "local"
        if service_name in services_with_local_runtime or indentation == ""
        else "containerized"
    )

    output = [
        f"{indentation}{Color.BOLD}{service_name}{Color.RESET}:",
        f"{indentation}{BASE_INDENTATION}Type: service",
        f"{indentation}{BASE_INDENTATION}Runtime: {runtime}",
    ]

    for dependency in sorted(
        dependencies, key=lambda d: (d.dependency_type.value, d.name)
    ):
        if dependency.name in services_with_local_runtime:
            output.append(
                process_service_with_local_runtime(
                    dependency,
                    indentation + BASE_INDENTATION,
                )
            )
        else:
            output.append(
                process_service_with_containerized_runtime(
                    dependency,
                    process_statuses,
                    docker_compose_service_to_status,
                    indentation + BASE_INDENTATION,
                    dependency_graph,
                )
            )
    return "\n".join(output)


def process_service_with_local_runtime(
    dependency: DependencyNode,
    indentation: str,
) -> str:
    output = []
    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))

    if dependency.name in started_services:
        return handle_started_service(dependency, indentation)
    elif dependency.name in starting_services:
        output.append(f"{indentation}{Color.BOLD}{dependency.name}{Color.RESET}:")
        output.append(f"{indentation}{BASE_INDENTATION}Type: service")
        output.append(f"{indentation}{BASE_INDENTATION}Status: starting")
        output.append(f"{indentation}{BASE_INDENTATION}Runtime: local")
    else:
        output.append(f"{indentation}{Color.BOLD}{dependency.name}{Color.RESET}:")
        output.append(f"{indentation}{BASE_INDENTATION}Type: service")
        output.append(f"{indentation}{BASE_INDENTATION}Status: N/A")
        output.append(f"{indentation}{BASE_INDENTATION}Runtime: local")
    return "\n".join(output)


def process_service_with_containerized_runtime(
    dependency: DependencyNode,
    process_statuses: dict[str, ProcessInfo],
    docker_compose_service_to_status: dict[str, ServiceStatusOutput],
    indentation: str,
    dependency_graph: DependencyGraph,
) -> str:
    if len(dependency_graph.graph[dependency]) > 0:
        return generate_service_status_tree(
            dependency.name,
            process_statuses,
            dependency_graph,
            docker_compose_service_to_status,
            indentation,
        )
    else:
        return generate_service_status_details(
            dependency, process_statuses, docker_compose_service_to_status, indentation
        )


def parse_docker_compose_status(
    status_json_results: list[subprocess.CompletedProcess[str]],
) -> dict[str, ServiceStatusOutput]:
    """Parse the JSON output from docker-compose status command."""
    docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {}
    for status_json in status_json_results:
        if not status_json.stdout:
            continue
        docker_compose_service_status_output = status_json.stdout.split("\n")[:-1]
        for docker_compose_service_status in docker_compose_service_status_output:
            docker_compose_service_status_json = json.loads(
                docker_compose_service_status
            )
            compose_service = docker_compose_service_status_json["Service"]
            docker_compose_service_to_status[
                compose_service
            ] = docker_compose_service_status_json

    return docker_compose_service_to_status


def generate_service_status_details(
    dependency: DependencyNode,
    process_statuses: dict[str, ProcessInfo],
    docker_compose_service_to_status: dict[str, ServiceStatusOutput],
    indentation: str,
) -> str:
    output = [f"{indentation}{Color.BOLD}{dependency.name}{Color.RESET}:"]

    # Handle supervisor dependencies
    if dependency.dependency_type == DependencyType.SUPERVISOR:
        return generate_supervisor_status_details(
            dependency, process_statuses, indentation
        )

    if dependency.name not in docker_compose_service_to_status:
        return "\n".join(
            [
                *output,
                (f"{indentation}{BASE_INDENTATION}Type: container"),
                f"{indentation}{BASE_INDENTATION}Status: N/A",
            ]
        )

    service_status = docker_compose_service_to_status[dependency.name]
    details = [
        "Type: container",
        f"Status: {service_status.get('State', 'N/A')}",
        f"Health: {format_health(service_status.get('Health', 'N/A'))}",
        f"Container: {service_status.get('Name', 'N/A')}",
        f"Uptime: {service_status.get('RunningFor', 'N/A')}",
    ]

    output.extend(f"{indentation}{BASE_INDENTATION}{detail}" for detail in details)

    if service_ports := service_status.get("Publishers", []):
        output.append(f"{indentation}{BASE_INDENTATION}Ports:")
        for service_port in service_ports:
            output.append(
                f"{indentation}{BASE_INDENTATION}{BASE_INDENTATION}{service_port['URL']}:{service_port['PublishedPort']} -> {service_port['TargetPort']}/{service_port['Protocol']}"
            )

    return "\n".join(output)


def handle_started_service(dependency: DependencyNode, indentation: str) -> str:
    try:
        service_with_local_runtime = find_matching_service(dependency.name)
    except (ConfigError, ServiceNotFoundError) as e:
        capture_exception(e)
        return "\n".join(
            [
                f"{indentation}{Color.BOLD}{dependency.name}{Color.RESET}:",
                f"{indentation}{BASE_INDENTATION}Type: service",
                f"{indentation}{BASE_INDENTATION}Status: N/A",
                f"{indentation}{BASE_INDENTATION}Runtime: local",
            ]
        )
    service_output = get_status_for_service(service_with_local_runtime, {})
    return "\n".join(
        [f"{indentation}{line}" for line in service_output.splitlines()],
    )


def format_health(health: str) -> str:
    """Format the health status for display."""
    color = (
        Color.GREEN
        if health.lower() == "healthy"
        else Color.RED
        if health.lower() == "unhealthy"
        else Color.YELLOW
    )
    return f"{color}{health}{Color.RESET}"


def generate_supervisor_status_details(
    dependency: DependencyNode,
    process_statuses: dict[str, ProcessInfo],
    indentation: str,
) -> str:
    """Generate status details for supervisor dependencies."""
    output = [f"{indentation}{Color.BOLD}{dependency.name}{Color.RESET}:"]

    process_info = process_statuses.get(dependency.name)

    if process_info is None:
        return "\n".join(
            [
                *output,
                f"{indentation}{BASE_INDENTATION}Type: process",
                f"{indentation}{BASE_INDENTATION}Status: N/A (process not found)",
            ]
        )

    uptime_str = format_uptime(process_info["uptime"])

    details = [
        "Type: process",
        f"Status: {process_info['state_name'].lower()}",
        f"PID: {process_info['pid'] if process_info['pid'] > 0 else 'N/A'}",
        f"Uptime: {uptime_str}",
    ]

    output.extend(f"{indentation}{BASE_INDENTATION}{detail}" for detail in details)

    return "\n".join(output)


def format_uptime(uptime_seconds: int) -> str:
    """Format uptime seconds into a human-readable string."""
    SECONDS_PER_MINUTE = 60
    SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE

    td = timedelta(seconds=uptime_seconds)
    days = td.days
    hours, remainder = divmod(td.seconds, SECONDS_PER_HOUR)
    minutes, seconds = divmod(remainder, SECONDS_PER_MINUTE)

    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    elif hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"
