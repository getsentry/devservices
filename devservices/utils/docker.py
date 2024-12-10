from __future__ import annotations

import subprocess

from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError


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


def get_matching_containers(label: str) -> list[str]:
    """
    Returns a list of container IDs with the given label
    """
    check_docker_daemon_running()
    try:
        return (
            subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    f"label={label}",
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
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


def stop_matching_containers(label: str, should_remove: bool = False) -> None:
    """
    Stops all containers with the given label.
    If should_remove is True, the containers will be removed.
    """
    matching_containers = get_matching_containers(label)
    if len(matching_containers) == 0:
        return
    try:
        subprocess.run(
            ["docker", "stop"] + matching_containers,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            command=f"docker stop {' '.join(matching_containers)}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    if should_remove:
        try:
            subprocess.run(
                ["docker", "rm"] + matching_containers,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            raise DockerError(
                command=f"docker rm {' '.join(matching_containers)}",
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e
