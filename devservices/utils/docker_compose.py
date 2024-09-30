from __future__ import annotations

import os
import re
import subprocess
from typing import cast

from packaging import version

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import MINIMUM_DOCKER_COMPOSE_VERSION
from devservices.exceptions import DockerComposeError
from devservices.utils.services import Service


def check_docker_compose_version() -> None:
    cmd = ["docker", "compose", "version", "--short"]
    try:
        # Run the docker compose version command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        # Extract the version number from the output
        version_output = result.stdout.strip()

        # Use regex to find the version number
        pattern = r"^(\d+\.\d+\.\d+)"

        match = re.search(pattern, version_output)
        if match:
            # There is a chance that Any type is returned, so cast this
            docker_compose_version = cast(str, match.group(1))
        else:
            docker_compose_version = None

    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )

    if docker_compose_version is None:
        print("Unable to detect docker compose version")
        exit(1)
    elif version.parse(docker_compose_version) < version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        print("Docker compose version unsupported, please upgrade to >= 2.21.0")
        exit(1)


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
