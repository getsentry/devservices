from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from collections.abc import Callable
from typing import cast

from packaging import version

from devservices.configs.service_config import load_service_config_from_file
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DOCKER_COMPOSE_DOWNLOAD_URL
from devservices.constants import DOCKER_USER_PLUGIN_DIR
from devservices.constants import LOGGER_NAME
from devservices.constants import MINIMUM_DOCKER_COMPOSE_VERSION
from devservices.exceptions import BinaryInstallError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import DockerComposeInstallationError
from devservices.utils.console import Console
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker import check_docker_daemon_running
from devservices.utils.install_binary import install_binary
from devservices.utils.services import Service


def install_docker_compose() -> None:
    console = Console()
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
    os.makedirs(DOCKER_USER_PLUGIN_DIR, exist_ok=True)

    try:
        install_binary(
            binary_name,
            destination,
            MINIMUM_DOCKER_COMPOSE_VERSION,
            url,
        )
    except BinaryInstallError as e:
        raise DockerComposeInstallationError(f"Failed to install Docker Compose: {e}")

    console.success(
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

    console.success(f"Verified Docker Compose installation: v{version}")


def check_docker_compose_version() -> None:
    console = Console()
    # Throw an error if docker daemon isn't running
    check_docker_daemon_running()
    try:
        # Run the docker compose version command
        result = subprocess.run(
            ["docker", "compose", "version", "--short"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        result = None
        console.warning(
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
        console.warning(
            f"Unable to detect Docker Compose version, attempting to install v{MINIMUM_DOCKER_COMPOSE_VERSION}"
        )
    elif version.parse(docker_compose_version) != version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        console.warning(
            f"Docker Compose version v{docker_compose_version} unsupported, attempting to install v{MINIMUM_DOCKER_COMPOSE_VERSION}"
        )
    elif version.parse(docker_compose_version) == version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        return
    install_docker_compose()


# TODO: Consider removing this in favor of in house logic for determining non-remote services
def _get_non_remote_services(
    service_config_path: str, current_env: dict[str, str]
) -> set[str]:
    config_command = [
        "docker",
        "compose",
        "-f",
        service_config_path,
        "config",
        "--services",
    ]
    try:
        config_services = subprocess.check_output(
            config_command, text=True, env=current_env
        )
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(config_command),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    return set(config_services.splitlines())


def get_docker_compose_commands_to_run(
    service: Service,
    remote_dependencies: list[InstalledRemoteDependency],
    current_env: dict[str, str],
    command: str,
    options: list[str],
    service_config_file_path: str,
    mode_dependencies: list[str],
) -> list[list[str]]:
    docker_compose_commands = []
    create_docker_compose_command: Callable[[str, str, set[str]], list[str]] = (
        lambda name, config_path, services_to_use: [
            "docker",
            "compose",
            "-p",
            name,
            "-f",
            config_path,
            command,
        ]
        + sorted(list(services_to_use))  # Sort the services to prevent flaky tests
        + options
    )
    for dependency in remote_dependencies:
        # TODO: Consider passing in service config in InstalledRemoteDependency instead of loading it here
        dependency_service_config = load_service_config_from_file(dependency.repo_path)
        dependency_config_path = os.path.join(
            dependency.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
        )
        non_remote_services = _get_non_remote_services(
            dependency_config_path, current_env
        )
        services_to_use = non_remote_services.intersection(
            set(dependency_service_config.modes[dependency.mode])
        )
        docker_compose_commands.append(
            create_docker_compose_command(
                dependency_service_config.service_name,
                dependency_config_path,
                services_to_use,
            )
        )

    # Add docker compose command for the top level service
    non_remote_services = _get_non_remote_services(
        service_config_file_path, current_env
    )
    services_to_use = non_remote_services.intersection(set(mode_dependencies))
    if len(services_to_use) > 0:
        docker_compose_commands.append(
            create_docker_compose_command(
                service.name, service_config_file_path, services_to_use
            )
        )
    return docker_compose_commands


def run_cmd(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    logger = logging.getLogger(LOGGER_NAME)
    try:
        logger.debug(f"Running command: {' '.join(cmd)}")
        return subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
