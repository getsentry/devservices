from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List
from typing import TYPE_CHECKING

from exceptions import ConfigNotFoundError
from exceptions import ConfigParseError
from exceptions import ConfigValidationError
from exceptions import ServiceNotFoundError
from utils.devenv import get_coderoot

if TYPE_CHECKING:
    from configs.service_config import ServiceConfig


@dataclass
class Service:
    name: str
    repo_path: str
    service_config: ServiceConfig


def get_local_services(coderoot: str) -> List[Service]:
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
                service_config=service_config,
            )
        )
    return services


def find_matching_service(service_name: str) -> Service:
    """Find a service with the given name."""
    coderoot = get_coderoot()
    services = get_local_services(coderoot)
    for service in services:
        if service.name.lower() == service_name.lower():
            return service
    raise ServiceNotFoundError(f'Service "{service_name}" not found')
