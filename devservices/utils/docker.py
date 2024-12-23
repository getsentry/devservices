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
        try:
            subprocess.run(
                ["docker", "rm"] + containers,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as e:
            raise DockerError(
                command=f"docker rm {' '.join(containers)}",
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e
