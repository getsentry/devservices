from __future__ import annotations

import os
import subprocess

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DockerComposeError
from devservices.utils.services import Service


def get_active_docker_compose_projects() -> list[str]:
    cmd = ["docker", "compose", "ls", "-q"]
    try:
        running_projects = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )
    # docker compose ls always returns newline delimited string with an extra newline at the end
    return running_projects.split("\n")[:-1]


def run_docker_compose_command(
    service: Service, command: str
) -> subprocess.CompletedProcess[str]:
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    cmd = [
        "docker",
        "compose",
        "-p",
        service.name,
        "-f",
        service_config_file_path,
    ] + command.split()
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=command,
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )
