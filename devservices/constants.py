from __future__ import annotations

import os

MINIMUM_DOCKER_COMPOSE_VERSION = "2.21.0"
DEVSERVICES_DIR_NAME = "devservices"
CONFIG_FILE_NAME = "config.yml"

DEVSERVICES_LOCAL_DIR = os.path.expanduser("~/.local/share/sentry-devservices")
DEVSERVICES_LOCAL_DEPENDENCIES_DIR = os.path.join(DEVSERVICES_LOCAL_DIR, "dependencies")
