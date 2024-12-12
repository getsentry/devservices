from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.request import urlopen

from devservices.constants import DEVSERVICES_CACHE_DIR
from devservices.constants import DEVSERVICES_LATEST_VERSION_CACHE_FILE
from devservices.constants import DEVSERVICES_LATEST_VERSION_CACHE_TTL
from devservices.constants import DEVSERVICES_RELEASES_URL


def _delete_cached_version() -> None:
    os.remove(DEVSERVICES_LATEST_VERSION_CACHE_FILE)


def _get_cached_version() -> str | None:
    if not os.path.exists(DEVSERVICES_LATEST_VERSION_CACHE_FILE):
        return None
    try:
        with open(DEVSERVICES_LATEST_VERSION_CACHE_FILE, "r", encoding="utf-8") as f:
            cached_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _delete_cached_version()
        return None

    timestamp = cached_data["timestamp"]
    cached_latest_version = cached_data["latest_version"]

    try:
        cached_time = datetime.fromisoformat(timestamp)
    except ValueError:
        _delete_cached_version()
        return None

    if (
        isinstance(cached_latest_version, str)
        and datetime.now() - cached_time < DEVSERVICES_LATEST_VERSION_CACHE_TTL
    ):
        return cached_latest_version

    # If the cache file exists but is stale or has an invalid version,
    # remove it.
    _delete_cached_version()
    return None


def _set_cached_version(latest_version: str) -> None:
    with open(DEVSERVICES_LATEST_VERSION_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "latest_version": latest_version,
                "timestamp": datetime.now().isoformat(),
            },
            f,
        )


def check_for_update() -> str | None:
    os.makedirs(DEVSERVICES_CACHE_DIR, exist_ok=True)

    cached_version = _get_cached_version()
    if cached_version is not None:
        return cached_version

    with urlopen(DEVSERVICES_RELEASES_URL) as response:
        if response.status == 200:
            data = json.loads(response.read())
            latest_version = str(data["tag_name"])

            _set_cached_version(latest_version)

            return latest_version
    return None
