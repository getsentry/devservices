from __future__ import annotations

import subprocess

from exceptions import DockerComposeError


def run_docker_compose_command(command: str) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose"] + command.split()
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=command,
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )
