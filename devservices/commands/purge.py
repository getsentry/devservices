from __future__ import annotations

import os
import shutil
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.configs.service_config import load_service_config_from_file
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.constants import DOCKER_NETWORK_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
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
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("purge", help="Purge the local devservices cache")
    parser.add_argument(
        "service_name",
        nargs="?",
        help="Service name to purge (optional, purges all if not specified)",
        default=None,
    )
    parser.set_defaults(func=purge)


def _get_service_cache_paths(service_name: str) -> list[str]:
    """Find cache directory paths for a given service name."""

    cache_paths: list[str] = []
    dependencies_cache_dir = os.path.join(
        DEVSERVICES_DEPENDENCIES_CACHE_DIR, DEPENDENCY_CONFIG_VERSION
    )

    if not os.path.exists(dependencies_cache_dir):
        return cache_paths

    for repo_name in os.listdir(dependencies_cache_dir):
        repo_path = os.path.join(dependencies_cache_dir, repo_name)
        if not os.path.isdir(repo_path):
            continue

        try:
            service_config = load_service_config_from_file(repo_path)
            if service_config.service_name == service_name:
                cache_paths.append(repo_path)
        except (ConfigNotFoundError, ConfigParseError, ConfigValidationError):
            # Skip invalid configs
            continue

    return cache_paths


def purge(args: Namespace) -> None:
    """Purge the local devservices state and cache and remove all devservices containers and volumes."""
    console = Console()
    service_name = getattr(args, "service_name", None)

    if service_name:
        _purge_service(service_name, console)
    else:
        _purge_all(console)


def _purge_service(service_name: str, console: Console) -> None:
    """Purge a specific service."""
    state = State()

    # Warn user about potential dependency issues
    if not console.confirm(
        f"WARNING: Purging {service_name} may introduce issues with the dependency tree.\n"
        "Other services that depend on this service may stop working correctly.\n"
        "Do you want to continue?"
    ):
        console.info("Purge cancelled.")
        return

    state.remove_service_entry(service_name, StateTables.SERVICE_RUNTIME)

    try:
        service_containers = get_matching_containers(
            [
                DEVSERVICES_ORCHESTRATOR_LABEL,
                f"com.docker.compose.service={service_name}",
            ]
        )
    except DockerDaemonNotRunningError as e:
        console.warning(str(e))
        service_containers = []
    except DockerError as de:
        console.failure(f"Failed to get containers for {service_name}: {de.stderr}")
        exit(1)

    if len(service_containers) == 0:
        console.warning(f"No containers found for {service_name}")
    else:
        try:
            service_volumes = get_volumes_for_containers(service_containers)
        except DockerError as e:
            console.failure(f"Failed to get volumes for {service_name}: {e.stderr}")
            exit(1)

        with Status(
            lambda: console.warning(f"Stopping {service_name} containers"),
            lambda: console.success(f"{service_name} containers have been stopped"),
        ):
            try:
                stop_containers(service_containers, should_remove=True)
            except DockerError as e:
                console.failure(f"Failed to stop {service_name} containers: {e.stderr}")
                exit(1)

        console.warning(f"Removing {service_name} docker volumes")
        if len(service_volumes) == 0:
            console.success(f"No volumes found for {service_name}")
        else:
            try:
                remove_docker_resources("volume", list(service_volumes))
                console.success(f"{service_name} volumes removed")
            except DockerError as e:
                console.failure(f"Failed to remove {service_name} volumes: {e.stderr}")

    cache_paths = _get_service_cache_paths(service_name)
    if cache_paths:
        console.warning(f"Removing cache for {service_name}")
        for cache_path in cache_paths:
            try:
                shutil.rmtree(cache_path)
            except PermissionError as e:
                console.failure(f"Failed to remove cache at {cache_path}: {e}")
                exit(1)
        console.success(f"Cache for {service_name} has been removed")
    else:
        console.success(f"No cache found for {service_name}")

    console.success(f"{service_name} has been purged")


def _purge_all(console: Console) -> None:
    """Purge all devservices state, cache, containers, volumes, and networks."""
    if os.path.exists(DEVSERVICES_CACHE_DIR):
        try:
            shutil.rmtree(DEVSERVICES_CACHE_DIR)
        except PermissionError as e:
            console.failure(f"Failed to purge cache: {e}")
            exit(1)
    state = State()
    state.clear_state()

    try:
        devservices_containers = get_matching_containers(
            [DEVSERVICES_ORCHESTRATOR_LABEL]
        )
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
