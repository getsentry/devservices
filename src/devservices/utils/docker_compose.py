import subprocess


def run_docker_compose_command(command, service=None):
    cmd = ["docker", "compose"] + command.split()
    if service:
        cmd.append(service)
    return subprocess.run(cmd, check=True, capture_output=True, text=True)
