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
from pydantic import validator


class Dependency(BaseModel):
    description: str
    link: Optional[str] = None


class ServiceConfig(BaseModel):
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
    service_config: ServiceConfig = Field(alias="x-sentry-service-config")


def load_service_config(repo_path: Optional[str] = None) -> Config:
    """Load the service config for a repo."""
    if repo_path is None:
        current_dir = os.getcwd()
        config_path = os.path.join(
            current_dir, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config file not found in current directory: {config_path}"
            )
    else:
        config_path = os.path.join(
            repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config file not found in service directory: {config_path}"
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
