from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional

import yaml
from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from exceptions import ConfigNotFoundError
from exceptions import ConfigParseError
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


def load_service_config_from_file(repo_path: str) -> ServiceConfig:
    config_path = os.path.join(
        repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    if not os.path.exists(config_path):
        raise ConfigNotFoundError(
            f"Config file not found in current directory: {config_path}"
        )
    with open(config_path, "r") as stream:
        try:
            config = yaml.safe_load(stream)
            service_config_data = config.get("x-sentry-service-config", {})
            dependencies = {
                key: Dependency(**value)
                for key, value in service_config_data.get("dependencies", {}).items()
            }
            service_config = ServiceConfig(
                version=service_config_data.get("version"),
                service_name=service_config_data.get("service_name"),
                dependencies=dependencies,
                modes=service_config_data.get("modes", {}),
            )

            return service_config
        except FileNotFoundError as fnf_error:
            raise ConfigNotFoundError(
                f"Config file not found: {config_path}"
            ) from fnf_error
        except yaml.YAMLError as yml_error:
            raise ConfigParseError(
                f"Error parsing config file: {config_path}"
            ) from yml_error


def load_service_config() -> ServiceConfig:
    """Load the service config for the current directory."""
    return load_service_config_from_file(os.getcwd())
