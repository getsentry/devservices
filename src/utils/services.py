from __future__ import annotations

import os
from dataclasses import dataclass

from configs.service_config import ServiceConfig
from exceptions import ConfigNotFoundError
from exceptions import ConfigParseError
from exceptions import ConfigValidationError
from exceptions import ServiceNotFoundError
from utils.devenv import get_coderoot


@dataclass
class Service:
    name: str
    repo_path: str
    config: ServiceConfig


def get_local_services(coderoot: str) -> list[Service]:
    """Get a list of services in the coderoot."""
    from configs.service_config import load_service_config_from_file

    services = []
    for repo in os.listdir(coderoot):
        repo_path = os.path.join(coderoot, repo)
        try:
            service_config = load_service_config_from_file(repo_path)
        except (ConfigNotFoundError, ConfigParseError, ConfigValidationError):
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
        from configs.service_config import load_service_config_from_file

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
    raise ServiceNotFoundError(f'Service "{service_name}" not found')
