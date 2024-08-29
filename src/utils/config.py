from __future__ import annotations

import os
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import yaml
from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator
from pydantic import validator
from utils.devenv import get_code_root


class Dependency(BaseModel):
    description: str


class HealthCheck(BaseModel):
    test: str


class Ulimits(BaseModel):
    nofile: Dict[str, int]


class ServiceDefinition(BaseModel):
    image: str
    healthcheck: Optional[HealthCheck] = None
    ulimits: Optional[Ulimits] = None
    ports: Optional[List[str]] = None
    environment: Optional[Dict[str, str]] = None
    volumes: Optional[List[str]] = None


class DevservicesConfig(BaseModel):
    version: float
    service_name: str
    dependencies: Dict[str, Dependency]
    modes: Dict[str, List[str]]

    @validator("version")
    def check_version(cls, version: float) -> float:
        if version != 0.1:
            raise ValueError("Version must be 0.1")
        return version

    @validator("modes")
    def check_modes(
        cls,
        modes: Dict[str, List[str]],
        values: Dict[str, Union[float, str, Dict[str, Dependency]]],
    ) -> Dict[str, List[str]]:
        dependencies = values.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError("Dependencies must be a dictionary")
        for mode, services in modes.items():
            for service in services:
                if service not in dependencies:
                    raise ValueError(
                        f"Service '{service}' in mode '{mode}' is not defined in dependencies"
                    )
        return modes


class Config(BaseModel):
    devservices_config: DevservicesConfig = Field(alias="x-sentry-devservices-config")
    services: Dict[str, ServiceDefinition]
    volumes: Optional[Dict[str, None]]

    @model_validator(mode="after")
    def check_services_match(self) -> Config:
        dev_config = self.devservices_config
        services = self.services

        # Check if all dependencies are defined in services
        for service in dev_config.dependencies:
            if service not in services:
                raise ValueError(
                    f"Service '{service}' defined in x-sentry-devservices-config is not present in services"
                )

        # Check if all services are defined in dependencies
        for service in services:
            if service not in dev_config.dependencies:
                raise ValueError(
                    f"Service '{service}' defined in services is not present in x-sentry-devservices-config dependencies"
                )

        return self


def load_devservices_config(service_name: Optional[str]) -> Config:
    """Load the devservices config for a service."""
    if not service_name:
        current_dir = os.getcwd()
        config_path = os.path.join(
            current_dir, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config file not found in current directory: {config_path}"
            )
    else:
        code_root = get_code_root()
        service_path = os.path.join(code_root, service_name)
        config_path = os.path.join(
            service_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config file for {service_name} not found from code root: {config_path}"
            )
    with open(config_path, "r") as stream:
        try:
            config = yaml.safe_load(stream)
            return Config(**config)
        except FileNotFoundError as fnf:
            raise FileNotFoundError(f"Config file not found: {config_path}") from fnf
        except yaml.YAMLError as yml_error:
            raise yaml.YAMLError(
                f"Error parsing config file: {config_path}"
            ) from yml_error
