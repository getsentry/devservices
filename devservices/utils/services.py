from __future__ import annotations

import os
from dataclasses import dataclass

from devservices.configs.service_config import ServiceConfig
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.devenv import get_coderoot


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
        except (ConfigParseError, ConfigValidationError) as e:
            console.warning(f"{repo} was found with an invalid config: {e}")
            continue
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
