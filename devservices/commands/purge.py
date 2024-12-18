from __future__ import annotations

import os
import shutil
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.constants import DEVSERVICES_CACHE_DIR
from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.constants import DOCKER_NETWORK_NAME
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import get_volumes_for_containers
from devservices.utils.docker import stop_containers
from devservices.utils.state import State


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("purge", help="Purge the local devservices cache")
    parser.set_defaults(func=purge)


def purge(_args: Namespace) -> None:
    """Purge the local devservices cache."""
    console = Console()

    if os.path.exists(DEVSERVICES_CACHE_DIR):
        try:
            shutil.rmtree(DEVSERVICES_CACHE_DIR)
        except PermissionError as e:
            console.failure(f"Failed to purge cache: {e}")
            exit(1)
    state = State()
    state.clear_state()
    try:
        devservices_containers = get_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL)
    except DockerError as e:
        console.failure(f"Failed to get devservices containers {e}")
        exit(1)
    try:
        devservices_volumes = get_volumes_for_containers(devservices_containers)
    except DockerError as e:
        console.failure(f"Failed to get devservices volumes {e}")
        exit(1)
    with Status(
        lambda: console.warning("Stopping all running devservices containers"),
        lambda: console.success("All running devservices containers have been stopped"),
    ):
        try:
            stop_containers(devservices_containers, should_remove=True)
        except DockerDaemonNotRunningError:
            console.warning("The docker daemon is not running, no containers to stop")
        except DockerError as e:
            console.failure(f"Failed to stop running devservices containers {e.stderr}")
            exit(1)

    console.warning("Removing any devservices docker volumes")
    if len(devservices_volumes) == 0:
        console.success("No devservices volumes found to remove")
    else:
        subprocess.run(
            ["docker", "volume", "rm", *devservices_volumes],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.success("All devservices volumes removed")

    console.warning("Removing any devservices networks")
    devservices_networks = (
        subprocess.check_output(
            [
                "docker",
                "network",
                "ls",
                "--filter",
                f"name={DOCKER_NETWORK_NAME}",
                "--format",
                "{{.ID}}",
            ]
        )
        .decode()
        .strip()
        .splitlines()
    )
    if len(devservices_networks) == 0:
        console.success("No devservices networks found to remove")
    for network in devservices_networks:
        subprocess.run(
            ["docker", "network", "rm", network],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.success(f"Network {network} removed")

    console.success("The local devservices cache and state has been purged")
