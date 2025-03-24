from __future__ import annotations

import concurrent.futures
import subprocess
import time
from typing import NamedTuple

from devservices.constants import HEALTHCHECK_INTERVAL
from devservices.constants import HEALTHCHECK_TIMEOUT
from devservices.exceptions import ContainerHealthcheckFailedError
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.console import Status


class ContainerNames(NamedTuple):
    name: str
    short_name: str


def check_docker_daemon_running() -> None:
    """Checks if the Docker daemon is running. Raises DockerDaemonNotRunningError if not."""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DockerDaemonNotRunningError from e


def check_all_containers_healthy(
    status: Status, containers: list[ContainerNames]
) -> None:
    """Ensures all containers are healthy."""
    status.info("Waiting for all containers to be healthy")
    with concurrent.futures.ThreadPoolExecutor() as healthcheck_executor:
        futures = [
            healthcheck_executor.submit(wait_for_healthy, container, status)
            for container in containers
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def wait_for_healthy(container: ContainerNames, status: Status) -> None:
    """
    Polls a Docker container's health status until it becomes healthy or a timeout is reached.
    """
    start = time.time()
    while time.time() - start < HEALTHCHECK_TIMEOUT:
        # Run docker inspect to get the container's health status
        try:
            # For containers with no healthchecks, the output will be "unknown"
            result = subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    container.name,
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except subprocess.CalledProcessError as e:
            raise DockerError(
                command=f"docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' {container.name}",
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e

        if result == "healthy":
            status.info(f"{container.short_name} is healthy")
            return
        if result == "unknown":
            status.warning(
                f"WARNING: Container {container.short_name} does not have a healthcheck"
            )
            return

        # If not healthy, wait and try again
        time.sleep(HEALTHCHECK_INTERVAL)

    raise ContainerHealthcheckFailedError(container.short_name, HEALTHCHECK_TIMEOUT)


def get_matching_containers(label: str) -> list[str]:
    """
    Returns a list of container names with the given label
    """
    check_docker_daemon_running()
    try:
        return (
            subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "-q",
                    "--filter",
                    f"label={label}",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
            .splitlines()
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker ps -q --filter label={label}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e


def get_matching_networks(name: str) -> list[str]:
    """
    Returns a list of network IDs with the given name
    """
    check_docker_daemon_running()
    try:
        return (
            subprocess.check_output(
                [
                    "docker",
                    "network",
                    "ls",
                    "--filter",
                    f"name={name}",
                    "--format",
                    "{{.ID}}",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
            .splitlines()
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker network ls --filter name={name} --format '{{.ID}}'",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e


def get_volumes_for_containers(containers: list[str]) -> set[str]:
    """
    Returns a set of volume names for the given containers.
    """
    if len(containers) == 0:
        return set()
    try:
        return {
            volume
            for volume in subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{ range .Mounts }}{{ .Name }}\n{{ end }}",
                    *containers,
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
            .splitlines()
            if volume
        }
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker inspect --format '{{ range .Mounts }}{{ .Name }}\n{{ end }}' {' '.join(containers)}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e


def stop_containers(containers: list[str], should_remove: bool = False) -> None:
    """
    Stops the given containers.
    If should_remove is True, the containers will be removed.
    """
    if len(containers) == 0:
        return
    try:
        subprocess.run(
            ["docker", "stop"] + containers,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker stop {' '.join(containers)}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    if should_remove:
        remove_docker_resources("container", containers)


def remove_docker_resources(resource_type: str, resources: list[str]) -> None:
    """
    Removes the given Docker resources.
    """
    try:
        subprocess.run(
            ["docker", resource_type, "rm", *resources],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker {resource_type} rm {' '.join(resources)}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
