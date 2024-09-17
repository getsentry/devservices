from __future__ import annotations

import json
import os
import sys
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DOCKER_COMPOSE_FILE_NAME
from devservices.exceptions import DockerComposeError
from devservices.utils.docker_compose import run_docker_compose_command
from devservices.utils.services import find_matching_service

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
        health = service.get("Health", "N/A")
        ports = service.get("Publishers", [])
        running_for = service.get("RunningFor", "N/A")

        output.append(f"{name}")
        output.append(f"Status: {state}")
        output.append(f"Health: {health}")
        output.append(f"Uptime: {running_for}")

        if ports:
            output.append("Ports:")
            for port in ports:
                output.append(
                    f"  {port['PublishedPort']} -> {port['TargetPort']}/{port['Protocol']}"
                )
        else:
            output.append("No ports exposed")

        output.append("")  # Empty line for readability

    return "\n".join(output)


def status(args: Namespace) -> None:
    """Start a service and its dependencies."""
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_view = "default"
    mode_dependencies = " ".join(modes[mode_to_view])
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    try:
        status_json = run_docker_compose_command(
            f"-f {service_config_file_path} ps {mode_dependencies} --format json"
        ).stdout
    except DockerComposeError as dce:
        print(f"Failed to get status for {service.name}: {dce.stderr}")
        exit(1)
    # If the service is not running, the status_json will be empty
    if not status_json:
        print(f"{service.name} is not running")
        return
    output = f"Service: {service.name}\n\n"
    output += format_status_output(status_json)
    output += "=" * LINE_LENGTH
    sys.stdout.write(output + "\n")
    sys.stdout.flush()
