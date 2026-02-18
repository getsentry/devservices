from __future__ import annotations

import os
from datetime import timedelta
from enum import StrEnum


class Color:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    NEGATIVE = "\033[7m"
    RESET = "\033[0m"


class DependencyType(StrEnum):
    SERVICE = "service"
    COMPOSE = "compose"
    SUPERVISOR = "supervisor"


MINIMUM_DOCKER_COMPOSE_VERSION = "2.29.7"
DEVSERVICES_DIR_NAME = "devservices"
CONFIG_FILE_NAME = "config.yml"
DOCKER_CONFIG_DIR = os.environ.get("DOCKER_CONFIG", os.path.expanduser("~/.docker"))
DOCKER_USER_PLUGIN_DIR = os.path.join(DOCKER_CONFIG_DIR, "cli-plugins/")

DEVSERVICES_CACHE_DIR = os.path.expanduser("~/.cache/sentry-devservices")
DEVSERVICES_LOCAL_DIR = os.path.expanduser("~/.local/share/sentry-devservices")
DEVSERVICES_DEPENDENCIES_CACHE_DIR = os.path.join(DEVSERVICES_CACHE_DIR, "dependencies")
DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY = "DEVSERVICES_DEPENDENCIES_CACHE_DIR"
DEVSERVICES_SUPERVISOR_CONFIG_DIR = os.path.join(DEVSERVICES_LOCAL_DIR, "supervisor")
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

# We mirror this in our GCP bucket since GitHub downloads can be flaky at times.
# gsutil cp docker-compose-darwin-aarch64 gs://sentry-dev-infra-assets/docker-compose/v2.29.7/docker-compose-darwin-aarch64
# gsutil cp docker-compose-linux-x86_64 gs://sentry-dev-infra-assets/docker-compose/v2.29.7/docker-compose-linux-x86_64
DOCKER_COMPOSE_DOWNLOAD_URL = (
    "https://storage.googleapis.com/sentry-dev-infra-assets/docker-compose"
)

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
SUPERVISOR_TIMEOUT = 10

# Sandbox (GCE) constants
SANDBOX_DEFAULT_ZONE = "us-central1-a"
SANDBOX_DEFAULT_MACHINE_TYPE = "e2-standard-8"
SANDBOX_IMAGE_FAMILY = "sentry-sandbox"
SANDBOX_IMAGE_PROJECT = "hubert-test-project"
SANDBOX_LABEL_KEY = "purpose"
SANDBOX_LABEL_VALUE = "sandbox"
SANDBOX_NETWORK_TAG = "sentry-sandbox"
SANDBOX_DISK_SIZE = 100
SANDBOX_DISK_TYPE = "pd-ssd"
SANDBOX_DEFAULT_PORTS = [8000]
SANDBOX_MAINTENANCE_SYNC_PATH = "/opt/sandbox/scripts/maintenance-sync.sh"
SANDBOX_REQUIRED_APIS = ["iap.googleapis.com", "compute.googleapis.com"]
SANDBOX_DEFAULT_LOG_LINES = 100
