from __future__ import annotations

import os
from dataclasses import dataclass

from sentry_sdk import logger as sentry_logger

from devservices.configs.service_config import ServiceConfig
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.devenv import get_coderoot
from devservices.utils.state import State
from devservices.utils.state import StateTables


@dataclass
class Service:
    name: str
    repo_path: str
    config: ServiceConfig


def get_local_services(coderoot: str) -> list[Service]:
    """Get a list of services in the coderoot."""
    from devservices.configs.service_config import load_service_config_from_file

    console = Console()

    services = []
    for repo in os.listdir(coderoot):
        repo_path = os.path.join(coderoot, repo)
        try:
            service_config = load_service_config_from_file(repo_path)
        except (ConfigParseError, ConfigValidationError):
            console.warning(f"{repo} was found with an invalid config")
            raise
        except ConfigNotFoundError:
            # Ignore repos that don't have devservices configs
            continue
        service_name = service_config.service_name
        services.append(
            Service(
                name=service_name,
                repo_path=repo_path,
                config=service_config,
            )
        )
    return services


def find_matching_service(service_name: str | None = None) -> Service:
    """Find a service with the given name."""
    if service_name is None:
        from devservices.configs.service_config import load_service_config_from_file

        repo_path = os.getcwd()
        service_config = load_service_config_from_file(repo_path)

        return Service(
            name=service_config.service_name,
            repo_path=repo_path,
            config=service_config,
        )
    coderoot = get_coderoot()
    services = get_local_services(coderoot)
    for service in services:
        if service.name.lower() == service_name.lower():
            return service
    unique_service_names = sorted(set(service.name for service in services))
    error_message = f"Service '{service_name}' not found."
    if len(unique_service_names) > 0:
        service_bullet_points = "\n".join(
            [f"- {service_name}" for service_name in unique_service_names]
        )
        error_message += "\nSupported services:\n" + service_bullet_points
    raise ServiceNotFoundError(error_message)


def get_active_service_names(clean_stale_entries: bool = False) -> set[str]:
    """Get the names of all services currently starting or started.

    Args:
        clean_stale_entries: If True, verify each service still exists on disk.
            Stale entries (services that no longer exist) are removed
            from the state database and excluded from the result.
    """
    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)

    if not clean_stale_entries:
        return active_services

    valid_services: set[str] = set()
    for service_name in active_services:
        try:
            find_matching_service(service_name)
            valid_services.add(service_name)
        except ServiceNotFoundError:
            sentry_logger.warning(
                "Stale service entry found in state database, removing",
                extra={"service_name": service_name},
            )
            state.remove_stale_service_entry(service_name)
    return valid_services
