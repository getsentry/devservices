from __future__ import annotations

import os
import platform
import re
import subprocess
from collections.abc import Callable
from typing import cast

from packaging import version

from devservices.configs.service_config import load_service_config_from_file
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
from devservices.utils.dependencies import get_installed_remote_dependencies
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.dependencies import verify_local_dependencies
from devservices.utils.install_binary import install_binary
from devservices.utils.services import Service


def get_active_docker_compose_projects() -> list[str]:
    cmd = ["docker", "compose", "ls", "-q"]
    try:
        running_projects = subprocess.check_output(cmd, text=True)
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


def _get_docker_compose_commands_to_run(
    service: Service,
    remote_dependencies: set[InstalledRemoteDependency],
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
    # Sort the remote dependencies by service name to ensure a deterministic order
    for dependency in sorted(remote_dependencies, key=lambda x: x.service_name):
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
    docker_compose_commands.append(
        create_docker_compose_command(
            service.name, service_config_file_path, services_to_use
        )
    )
    return docker_compose_commands


def run_docker_compose_command(
    service: Service,
    command: str,
    mode_dependencies: list[str],
    options: list[str] = [],
    force_update_dependencies: bool = False,
) -> list[subprocess.CompletedProcess[str]]:
    dependencies = list(service.config.dependencies.values())
    if force_update_dependencies:
        remote_dependencies = install_dependencies(dependencies)
    else:
        are_dependencies_valid = verify_local_dependencies(dependencies)
        if not are_dependencies_valid:
            # TODO: Figure out how to handle this case as installing dependencies may not be the right thing to do
            #       since the dependencies may have changed since the service was started.
            remote_dependencies = install_dependencies(dependencies)
        else:
            remote_dependencies = get_installed_remote_dependencies(dependencies)
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
    docker_compose_commands = _get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=remote_dependencies,
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    cmd_outputs = []
    for cmd in docker_compose_commands:
        try:
            cmd_outputs.append(
                subprocess.run(
                    cmd, check=True, capture_output=True, text=True, env=current_env
                )
            )
        except subprocess.CalledProcessError as e:
            raise DockerComposeError(
                command=command,
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e

    return cmd_outputs
