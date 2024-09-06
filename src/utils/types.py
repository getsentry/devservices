from __future__ import annotations

from dataclasses import dataclass

from configs.service_config import ServiceConfig


@dataclass
class Service:
    name: str
    repo_path: str
    service_config: ServiceConfig
