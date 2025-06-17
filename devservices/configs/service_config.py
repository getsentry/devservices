from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import fields

import yaml
from supervisor.options import ServerOptions

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.utils.supervisor import ProgramData
from devservices.utils.supervisor import SupervisorManager

VALID_VERSIONS = [0.1]


@dataclass
class RemoteConfig:
    repo_name: str
    branch: str
    repo_link: str
    mode: str = "default"


@dataclass
class Dependency:
    description: str
    dependency_type: DependencyType
    remote: RemoteConfig | None = None


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
    config_path = os.path.join(repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME)
    if not os.path.exists(config_path):
        raise ConfigNotFoundError(
            f"No devservices configuration found in {config_path}"
        )
    with open(config_path, "r", encoding="utf-8") as stream:
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

        docker_compose_services = config.get("services", {}).keys()

        supervisor_programs = load_supervisor_programs_from_programs_data(
            config_path,
            service_config_data.get("service_name"),
            config.get("x-programs", {}),
        )

        valid_dependency_keys = {field.name for field in fields(Dependency)}

        dependencies = {}

        try:
            for key, value in service_config_data.get("dependencies", {}).items():
                unexpected_keys = set(value.keys()) - valid_dependency_keys
                if unexpected_keys:
                    raise ConfigParseError(
                        f"Unexpected key(s) in dependency '{key}': {unexpected_keys}"
                    )
                if value.get("remote") is None:
                    if key in supervisor_programs:
                        dependency_type = DependencyType.SUPERVISOR
                    elif key in docker_compose_services:
                        dependency_type = DependencyType.COMPOSE
                    else:
                        raise ConfigValidationError(
                            f"Dependency '{key}' is not remote but is not defined in docker-compose services or x-programs"
                        )
                else:
                    dependency_type = DependencyType.SERVICE

                dependencies[key] = Dependency(
                    description=value.get("description"),
                    remote=(
                        RemoteConfig(**value.get("remote"))
                        if "remote" in value
                        else None
                    ),
                    dependency_type=dependency_type,
                )
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


def load_supervisor_programs_from_programs_data(
    service_config_path: str, service_name: str, programs_data: ProgramData
) -> set[str]:
    if not programs_data:
        return set()

    manager = SupervisorManager(
        service_name=service_name, service_config_path=service_config_path
    )
    opts = ServerOptions()
    opts.configfile = manager.config_file_path
    opts.process_config()
    return set([program.name for program in opts.process_group_configs])
