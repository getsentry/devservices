from __future__ import annotations

import subprocess

from devservices.exceptions import DockerDaemonNotRunningError


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


def stop_all_running_containers() -> None:
    check_docker_daemon_running()
    running_containers = (
        subprocess.check_output(["docker", "ps", "-q"], stderr=subprocess.DEVNULL)
        .decode()
        .strip()
        .splitlines()
    )
    if len(running_containers) == 0:
        return
    subprocess.run(
        ["docker", "stop"] + running_containers,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
