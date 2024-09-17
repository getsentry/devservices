from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DOCKER_COMPOSE_FILE_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError

VALID_VERSIONS = [0.1]


@dataclass
class Dependency:
    description: str
    link: str | None = None


@dataclass
class ServiceConfig:
    version: float
    service_name: str
    dependencies: dict[str, Dependency]
    modes: dict[str, list[str]]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.version:
            raise ConfigValidationError("Version is required in service config")

        if self.version not in VALID_VERSIONS:
            raise ConfigValidationError(
                f"Invalid version '{self.version}' in service config"
            )

        if not self.service_name:
            raise ConfigValidationError("Service name is required in service config")

        if "default" not in self.modes:
            raise ConfigValidationError("Default mode is required in service config")

        for mode, services in self.modes.items():
            if not isinstance(services, list):
                raise ConfigValidationError(f"Services in mode '{mode}' must be a list")
            for service in services:
                if service not in self.dependencies:
                    raise ConfigValidationError(
                        f"Service '{service}' in mode '{mode}' is not defined in dependencies"
                    )


def load_service_config_from_file(repo_path: str) -> ServiceConfig:
    config_path = os.path.join(
        repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    if not os.path.exists(config_path):
        raise ConfigNotFoundError(f"Config file not found in directory: {config_path}")
    with open(config_path, "r") as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as yml_error:
            raise ConfigParseError(
                f"Error parsing config file: {yml_error}"
            ) from yml_error

        if "x-sentry-service-config" not in config:
            raise ConfigParseError(
                "Config file does not contain 'x-sentry-service-config' key"
            )
        service_config_data = config.get("x-sentry-service-config")

        try:
            dependencies = {
                key: Dependency(**value)
                for key, value in service_config_data.get("dependencies", {}).items()
            }
        except TypeError as type_error:
            raise ConfigParseError(
                f"Error parsing service dependencies: {type_error}"
            ) from type_error

        service_config = ServiceConfig(
            version=service_config_data.get("version"),
            service_name=service_config_data.get("service_name"),
            dependencies=dependencies,
            modes=service_config_data.get("modes", {}),
        )

        return service_config
