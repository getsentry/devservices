from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional

from exceptions import ConfigValidationError


@dataclass
class Dependency:
    description: str
    link: Optional[str] = None


@dataclass
class ServiceConfig:
    version: float
    service_name: str
    dependencies: Dict[str, Dependency]
    modes: Dict[str, List[str]]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.version != 0.1:
            raise ConfigValidationError(
                f"Invalid version '{self.version}' in service config"
            )

        for mode, services in self.modes.items():
            for service in services:
                if service not in self.dependencies:
                    raise ConfigValidationError(
                        f"Service '{service}' in mode '{mode}' is not defined in dependencies"
                    )


@dataclass
class Config:
    service_config: ServiceConfig
