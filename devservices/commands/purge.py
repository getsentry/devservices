from __future__ import annotations

import os
import shutil
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
from devservices.utils.docker import get_matching_networks
from devservices.utils.docker import get_volumes_for_containers
from devservices.utils.docker import remove_docker_resources
from devservices.utils.docker import stop_containers
from devservices.utils.state import State


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("purge", help="Purge the local devservices cache")
    parser.set_defaults(func=purge)


def purge(_args: Namespace) -> None:
    """Purge the local devservices state and cache and remove all devservices containers and volumes."""
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
    except DockerDaemonNotRunningError as e:
        console.warning(str(e))
        return
    except DockerError as de:
        console.failure(f"Failed to get devservices containers {de.stderr}")
        exit(1)

    try:
        devservices_volumes = get_volumes_for_containers(devservices_containers)
    except DockerError as e:
        console.failure(f"Failed to get devservices volumes {e.stderr}")
        exit(1)

    with Status(
        lambda: console.warning("Stopping all devservices containers"),
        lambda: console.success("All devservices containers have been stopped"),
    ):
        try:
            stop_containers(devservices_containers, should_remove=True)
        except DockerError as e:
            console.failure(f"Failed to stop devservices containers {e.stderr}")
            exit(1)

    console.warning("Removing any devservices docker volumes")
    if len(devservices_volumes) == 0:
        console.success("No devservices volumes found to remove")
    else:
        try:
            remove_docker_resources("volume", list(devservices_volumes))
            console.success("All devservices volumes removed")
        except DockerError as e:
            # We don't want to exit here since we still want to try to remove the networks
            console.failure(f"Failed to remove devservices volumes {e.stderr}")

    console.warning("Removing any devservices networks")
    try:
        devservices_networks = get_matching_networks(DOCKER_NETWORK_NAME)
    except DockerError as e:
        console.failure(f"Failed to get devservices networks {e.stderr}")
        exit(1)
    if len(devservices_networks) == 0:
        console.success("No devservices networks found to remove")
    else:
        try:
            remove_docker_resources("network", devservices_networks)
            console.success("All devservices networks removed")
        except DockerError as e:
            console.failure(f"Failed to remove devservices networks {e.stderr}")
            exit(1)

    console.success("The local devservices cache and state has been purged")
