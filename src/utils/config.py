from __future__ import annotations

import os
from typing import Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator, validator

from constants import DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME


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
        dependencies: Dict[str, Dependency] = values.get("dependencies", {})
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


def load_devservices_config(service_path: str) -> Dict[str, Dict[str, str]]:
    """Load the devservices config for a service."""
    config_path = os.path.join(
        service_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
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
