from __future__ import annotations

import concurrent.futures
import json
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
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service

LINE_LENGTH = 40


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("status", help="View status of a service")
    parser.add_argument(
        "service_name",
        help="Name of the service to view status for",
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=status)


def format_status_output(status_json: str) -> str:
    # Docker compose ps is line delimited json, so this constructs this into an array we can use
    service_statuses = status_json.split("\n")[:-1]
    output = []
    output.append("-" * LINE_LENGTH)
    for service_status in service_statuses:
        service = json.loads(service_status)
        name = service["Service"]
        state = service["State"]
        container_name = service["Name"]
        health = service.get("Health", "N/A")
        ports = service.get("Publishers", [])
        running_for = service.get("RunningFor", "N/A")

        output.append(f"{name}")
        output.append(f"Container: {container_name}")
        output.append(f"Status: {state}")
        output.append(f"Health: {health}")
        output.append(f"Uptime: {running_for}")

        if ports:
            output.append("Ports:")
            for port in ports:
                output.append(
                    f"  {port['URL']}:{port['PublishedPort']} -> {port['TargetPort']}/{port['Protocol']}"
                )
        else:
            output.append("No ports exposed")

        output.append("")  # Empty line for readability

    return "\n".join(output)


def status(args: Namespace) -> None:
    """Get the status of a specified service."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)

    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_view = "default"
    mode_dependencies = modes[mode_to_view]

    try:
        remote_dependencies = install_and_verify_dependencies(service)
    except DependencyError as de:
        capture_exception(de)
        console.failure(str(de))
        exit(1)
    try:
        status_json_results = _status(service, remote_dependencies, mode_dependencies)
    except DockerComposeError as dce:
        capture_exception(dce)
        console.failure(f"Failed to get status for {service.name}: {dce.stderr}")
        exit(1)

    # Filter out empty stdout to help us determine if the service is running
    status_json_results = [
        status_json for status_json in status_json_results if status_json.stdout
    ]
    if len(status_json_results) == 0:
        console.warning(f"{service.name} is not running")
        return
    output = f"Service: {service.name}\n\n"
    for status_json in status_json_results:
        output += format_status_output(status_json.stdout)
    output += "=" * LINE_LENGTH
    console.info(output + "\n")


def _status(
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
            executor.submit(run_cmd, cmd, current_env)
            for cmd in docker_compose_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            cmd_outputs.append(future.result())

    return cmd_outputs
