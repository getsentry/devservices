from __future__ import annotations

import os

import yaml
from configs.types import Dependency
from configs.types import ServiceConfig
from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from exceptions import ConfigError
from exceptions import ConfigNotFoundError
from exceptions import ConfigParseError
from exceptions import ServiceNotFoundError
from utils.services import find_matching_service


def load_service_config_from_file(repo_path: str) -> ServiceConfig:
    config_path = os.path.join(
        repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    if not os.path.exists(config_path):
        raise ConfigNotFoundError(f"Config file not found in directory: {config_path}")
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


def load_service_config_from_current_directory() -> ServiceConfig:
    """Load the service config for the current directory."""
    return load_service_config_from_file(os.getcwd())


def load_service_config(service_name: str | None) -> ServiceConfig:
    if service_name is not None:
        try:
            service_config = find_matching_service(service_name).service_config
        except ServiceNotFoundError as e:
            print(e)
            return
    else:
        try:
            service_config = load_service_config_from_current_directory()
        except ConfigError as e:
            print(e)
            return
    return service_config
