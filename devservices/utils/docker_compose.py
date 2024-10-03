from __future__ import annotations

import os
import subprocess

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DEVSERVICES_LOCAL_DEPENDENCIES_DIR
from devservices.constants import DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY
from devservices.exceptions import DockerComposeError
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import verify_local_dependencies
from devservices.utils.services import Service


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
