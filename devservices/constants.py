from __future__ import annotations

import os
from datetime import timedelta

MINIMUM_DOCKER_COMPOSE_VERSION = "2.29.7"
DEVSERVICES_DIR_NAME = "devservices"
CONFIG_FILE_NAME = "config.yml"
DOCKER_CONFIG_DIR = os.environ.get("DOCKER_CONFIG", os.path.expanduser("~/.docker"))
DOCKER_USER_PLUGIN_DIR = os.path.join(DOCKER_CONFIG_DIR, "cli-plugins/")

DEVSERVICES_CACHE_DIR = os.path.expanduser("~/.cache/sentry-devservices")
DEVSERVICES_LOCAL_DIR = os.path.expanduser("~/.local/share/sentry-devservices")
DEVSERVICES_DEPENDENCIES_CACHE_DIR = os.path.join(DEVSERVICES_CACHE_DIR, "dependencies")
DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY = "DEVSERVICES_DEPENDENCIES_CACHE_DIR"
STATE_DB_FILE = os.path.join(DEVSERVICES_LOCAL_DIR, "state")
DEVSERVICES_ORCHESTRATOR_LABEL = "orchestrator=devservices"

DEPENDENCY_CONFIG_VERSION = "v1"
DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS = {
    "protocol.version": "2",
    "extensions.partialClone": "true",
    "core.sparseCheckout": "true",
}

DEVSERVICES_RELEASES_URL = (
    "https://api.github.com/repos/getsentry/devservices/releases/latest"
)
DOCKER_COMPOSE_DOWNLOAD_URL = "https://github.com/docker/compose/releases/download"
DEVSERVICES_DOWNLOAD_URL = "https://github.com/getsentry/devservices/releases/download"
BINARY_PERMISSIONS = 0o755
MAX_LOG_LINES = "100"
LOGGER_NAME = "devservices"
DOCKER_NETWORK_NAME = "devservices"

# Latest Version Cache
DEVSERVICES_LATEST_VERSION_CACHE_FILE = os.path.join(
    DEVSERVICES_CACHE_DIR, "latest_version.txt"
)
DEVSERVICES_LATEST_VERSION_CACHE_TTL = timedelta(minutes=15)
# Healthcheck timeout set to 2 minutes to account for slow healthchecks
HEALTHCHECK_TIMEOUT = 120
HEALTHCHECK_INTERVAL = 5
