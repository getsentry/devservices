from __future__ import annotations

import subprocess
from typing import Optional


def run_docker_compose_command(
    command: str, service: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose"] + command.split()
    if service:
        cmd.append(service)
    return subprocess.run(cmd, check=True, capture_output=True, text=True)
