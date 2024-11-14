from __future__ import annotations

import json
from urllib.request import urlopen


def check_for_update() -> str | None:
    url = "https://api.github.com/repos/getsentry/devservices/releases/latest"
    with urlopen(url) as response:
        if response.status == 200:
            data = json.loads(response.read().decode("utf-8"))
            latest_version = str(data["tag_name"])
            return latest_version
    return None
