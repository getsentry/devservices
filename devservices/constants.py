from __future__ import annotations

import os

MINIMUM_DOCKER_COMPOSE_VERSION = "2.21.0"
DEVSERVICES_DIR_NAME = "devservices"
CONFIG_FILE_NAME = "config.yml"

DEVSERVICES_CACHE_DIR = os.path.expanduser("~/.cache/sentry-devservices")
DEVSERVICES_LOCAL_DIR = os.path.expanduser("~/.local/share/sentry-devservices")
DEVSERVICES_DEPENDENCIES_CACHE_DIR = os.path.join(DEVSERVICES_CACHE_DIR, "dependencies")
DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY = "DEVSERVICES_DEPENDENCIES_CACHE_DIR"

DEPENDENCY_CONFIG_VERSION = "v1"
DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS = {
    "protocol.version": "2",
    "extensions.partialClone": "true",
    "core.sparseCheckout": "true",
}
