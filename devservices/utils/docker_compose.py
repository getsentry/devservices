from __future__ import annotations

import os
import re
import subprocess
from typing import cast

from packaging import version

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DEVSERVICES_LOCAL_DEPENDENCIES_DIR
from devservices.constants import DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY
from devservices.constants import MINIMUM_DOCKER_COMPOSE_VERSION
from devservices.exceptions import DockerComposeError
from devservices.exceptions import DockerComposeVersionError
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import verify_local_dependencies
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

    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
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

    if docker_compose_version is None:
        raise DockerComposeVersionError("Unable to detect docker compose version")
    elif version.parse(docker_compose_version) < version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        raise DockerComposeVersionError(
            f"Docker compose version unsupported, please upgrade to >= {MINIMUM_DOCKER_COMPOSE_VERSION}"
        )


def run_docker_compose_command(
    service: Service, command: str, force_update_dependencies: bool = False
) -> subprocess.CompletedProcess[str]:
    dependencies = list(service.config.dependencies.values())
    if force_update_dependencies:
        install_dependencies(dependencies)
    else:
        are_dependencies_valid = verify_local_dependencies(dependencies)
        if not are_dependencies_valid:
            # TODO: Figure out how to handle this case as installing dependencies may not be the right thing to do
            #       since the dependencies may have changed since the service was started.
            install_dependencies(dependencies)
    relative_local_dependency_directory = os.path.relpath(
        DEVSERVICES_LOCAL_DEPENDENCIES_DIR, service.repo_path
    )
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    # Set the environment variable for the local dependencies directory to be used by docker compose
    current_env = os.environ.copy()
    current_env[
        DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY
    ] = relative_local_dependency_directory
    cmd = [
        "docker",
        "compose",
        "-p",
        service.name,
        "-f",
        service_config_file_path,
    ] + command.split()
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            env=current_env,
        )
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=command,
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
