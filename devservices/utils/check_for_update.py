from __future__ import annotations

import json
import os
from datetime import datetime
from datetime import timedelta
from urllib.request import urlopen

from devservices.constants import DEVSERVICES_CACHE_DIR
from devservices.constants import DEVSERVICES_LATEST_VERSION_CACHE_FILE
from devservices.constants import DEVSERVICES_LATEST_VERSION_CACHE_TTL
from devservices.constants import DEVSERVICES_RELEASES_URL


def _delete_cached_version() -> None:
    if os.path.exists(DEVSERVICES_LATEST_VERSION_CACHE_FILE):
        os.remove(DEVSERVICES_LATEST_VERSION_CACHE_FILE)


def _get_cache_age() -> timedelta:
    if os.path.exists(DEVSERVICES_LATEST_VERSION_CACHE_FILE):
        file_modification_time = datetime.fromtimestamp(
            os.path.getmtime(DEVSERVICES_LATEST_VERSION_CACHE_FILE)
        )
        return datetime.now() - file_modification_time
    return timedelta.max


def _get_cached_version() -> str | None:
    cache_age = _get_cache_age()
    if cache_age < DEVSERVICES_LATEST_VERSION_CACHE_TTL:
        with open(DEVSERVICES_LATEST_VERSION_CACHE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    else:
        _delete_cached_version()
        return None


def _set_cached_version(latest_version: str) -> None:
    with open(DEVSERVICES_LATEST_VERSION_CACHE_FILE, "w", encoding="utf-8") as f:
        f.write(latest_version)


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
