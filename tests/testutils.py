from __future__ import annotations

from pathlib import Path

import yaml


def create_config_file(
    tmp_path: Path, config: dict[str, object] | dict[str, dict[str, object]]
) -> None:
    devservices_dir = Path(tmp_path, "devservices")
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, "docker-compose.yml")
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)
