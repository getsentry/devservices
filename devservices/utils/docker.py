from __future__ import annotations

import subprocess

from devservices.exceptions import DockerDaemonNotRunningError


def check_docker_daemon_running() -> None:
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise DockerDaemonNotRunningError(
            "Unable to connect to the docker daemon. Is the docker daemon running?"
        ) from e
