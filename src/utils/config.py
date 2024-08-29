from __future__ import annotations

from constants import DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME

import yaml
import os
from typing import Dict


def load_devservices_config(service_path: str) -> Dict[str, Dict]:
    """Load the devservices config for a service."""
    config_path = os.path.join(
        service_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r") as stream:
        try:
            config = yaml.safe_load(stream)
            devservices_config = config.get("x-sentry-devservices-config")
            if devservices_config is None:
                raise KeyError(
                    "Key 'x-sentry-devservices-config' not found in the config file."
                )
            return devservices_config
        except FileNotFoundError as fnf:
            raise FileNotFoundError(f"Config file not found: {config_path}") from fnf
        except yaml.YAMLError as yml_error:
            raise yaml.YAMLError(
                f"Error parsing config file: {config_path}"
            ) from yml_error
