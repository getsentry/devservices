from __future__ import annotations

import os
from typing import List

from configs.service_config import load_service_config
from pydantic import BaseModel


class Service(BaseModel):
    name: str
    repo_path: str


def get_local_services(coderoot: str) -> List[Service]:
    """Get a list of services in the coderoot."""
    services = []
    for repo in os.listdir(coderoot):
        repo_path = os.path.join(coderoot, repo)
        try:
            service_config = load_service_config(repo_path)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        service_name = service_config.service_config.service_name
        services.append(
            Service(
                name=service_name,
                repo_path=repo_path,
            )
        )
    return services


def find_matching_service(services: List[Service], service_name: str) -> Service:
    """Find a service with the given name."""
    for service in services:
        if service.name.lower() == service_name.lower():
            return service
    raise Exception(f'Service "{service_name}" not found')
