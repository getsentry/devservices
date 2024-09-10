from __future__ import annotations

import subprocess


def run_docker_compose_command(command: str) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose"] + command.split()
    return subprocess.run(cmd, check=True, capture_output=True, text=True)
