from __future__ import annotations

import os
import shutil
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.constants import DEVSERVICES_CACHE_DIR
from devservices.constants import DOCKER_NETWORK_NAME
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.docker import stop_all_running_containers
from devservices.utils.state import State


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("purge", help="Purge the local devservices cache")
    parser.set_defaults(func=purge)


def purge(_args: Namespace) -> None:
    """Purge the local devservices cache."""
    console = Console()

    # Prompt the user to stop all running containers
    should_stop_containers = console.confirm(
        "Warning: Purging stops all running containers and clears devservices state. Would you like to continue?"
    )
    if not should_stop_containers:
        console.warning("Purge canceled")
        return

    if os.path.exists(DEVSERVICES_CACHE_DIR):
        try:
            shutil.rmtree(DEVSERVICES_CACHE_DIR)
        except PermissionError as e:
            console.failure(f"Failed to purge cache: {e}")
            exit(1)
    state = State()
    state.clear_state()
    with Status(
        lambda: console.warning("Stopping all running containers"),
        lambda: console.success("All running containers have been stopped"),
    ):
        try:
            stop_all_running_containers()
        except DockerDaemonNotRunningError:
            console.warning("The docker daemon not running, no containers to stop")

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
