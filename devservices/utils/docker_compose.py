from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import cast

from packaging import version

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DOCKER_COMPOSE_DOWNLOAD_URL
from devservices.constants import DOCKER_USER_PLUGIN_DIR
from devservices.constants import MINIMUM_DOCKER_COMPOSE_VERSION
from devservices.exceptions import BinaryInstallError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import DockerComposeInstallationError
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import verify_local_dependencies
from devservices.utils.install_binary import install_binary
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


def install_docker_compose() -> None:
    # Determine the platform
    system = platform.system()
    machine = platform.machine()

    # Map machine architecture to Docker's naming convention
    arch_map = {
        "x86_64": "x86_64",
        "AMD64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "ARM64": "aarch64",
    }

    arch = arch_map.get(machine)
    if not arch:
        raise DockerComposeInstallationError(f"Unsupported architecture: {machine}")

    binary_name = "docker-compose"

    # Determine the download URL based on the platform
    if system == "Linux":
        binary_name_with_extension = f"docker-compose-linux-{arch}"
    elif system == "Darwin":
        binary_name_with_extension = f"docker-compose-darwin-{arch}"
    else:
        raise DockerComposeInstallationError(f"Unsupported operating system: {system}")

    url = f"{DOCKER_COMPOSE_DOWNLOAD_URL}/v{MINIMUM_DOCKER_COMPOSE_VERSION}/{binary_name_with_extension}"
    destination = os.path.join(DOCKER_USER_PLUGIN_DIR, binary_name)

    try:
        install_binary(
            binary_name,
            destination,
            MINIMUM_DOCKER_COMPOSE_VERSION,
            url,
        )
    except BinaryInstallError as e:
        raise DockerComposeInstallationError(f"Failed to install Docker Compose: {e}")

    print(
        f"Docker Compose {MINIMUM_DOCKER_COMPOSE_VERSION} installed successfully to {destination}"
    )

    # Verify the installation
    try:
        version = subprocess.run(
            ["docker", "compose", "version", "--short"], capture_output=True, text=True
        ).stdout
    except Exception as e:
        raise DockerComposeInstallationError(
            f"Failed to verify Docker Compose installation: {e}"
        )

    print(f"Verified Docker Compose installation: v{version}")


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
    except subprocess.CalledProcessError:
        result = None
        print(
            f"Docker Compose is not installed, attempting to install v{MINIMUM_DOCKER_COMPOSE_VERSION}"
        )

    # Extract the version number from the output
    version_output = result.stdout.strip() if result is not None else ""

    # Use regex to find the version number
    pattern = r"^(\d+\.\d+\.\d+)"

    match = re.search(pattern, version_output)
    if match:
        # There is a chance that Any type is returned, so cast this
        docker_compose_version = cast(str, match.group(1))
    else:
        docker_compose_version = None

    if docker_compose_version is None:
        print(
            f"Unable to detect Docker Compose version, attempting to install v{MINIMUM_DOCKER_COMPOSE_VERSION}"
        )
    elif version.parse(docker_compose_version) != version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        print(
            f"Docker Compose version v{docker_compose_version} unsupported, attempting to install v{MINIMUM_DOCKER_COMPOSE_VERSION}"
        )
    elif version.parse(docker_compose_version) == version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        return
    install_docker_compose()


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
