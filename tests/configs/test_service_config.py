from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from configs.service_config import load_service_config_from_file
from exceptions import ConfigNotFoundError
from exceptions import ConfigValidationError


@pytest.mark.parametrize(
    "service_name, dependencies, modes",
    [
        (
            "example-service",
            {"example-dependency": "Example dependency"},
            {"default": ["example-dependency"]},
        ),
        (
            "example-service",
            {
                "example-dependency": "Example dependency",
                "example-dependency-2": "Example dependency 2",
            },
            {"default": ["example-dependency", "example-dependency-2"]},
        ),
        (
            "example-service",
            {"example-dependency": "Example dependency"},
            {
                "default": ["example-dependency"],
                "debug": ["example-dependency"],
                "test": ["example-dependency"],
            },
        ),
    ],
)
def test_load_service_config_from_file(
    tmp_path: Path,
    service_name: str,
    dependencies: dict[str, str],
    modes: dict[str, list[str]],
) -> None:
    devservices_dir = tmp_path / "devservices"
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = devservices_dir / "docker-compose.yml"
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": service_name,
            "dependencies": {
                key: {"description": value} for key, value in dependencies.items()
            },
            "modes": modes,
        }
    }
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)
    # We pass the tmp_path rather than the tmp_file because the function expects the directory
    service_config = load_service_config_from_file(tmp_path)
    assert service_config.version == 0.1
    assert service_config.service_name == service_name
    assert len(service_config.dependencies) == len(dependencies)
    for key, value in dependencies.items():
        assert key in service_config.dependencies
        assert service_config.dependencies[key].description == value
    assert len(service_config.modes) == len(modes)
    assert "default" in service_config.modes
    for mode, services in modes.items():
        assert mode in service_config.modes
        assert service_config.modes[mode] == services


def test_load_service_config_from_file_missing_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigNotFoundError) as e:
        load_service_config_from_file(tmp_path)
    assert (
        str(e.value)
        == f"Config file not found in directory: {tmp_path / 'devservices' / 'docker-compose.yml'}"
    )


def test_load_service_config_from_file_invalid_version(tmp_path: Path) -> None:
    devservices_dir = tmp_path / "devservices"
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = devservices_dir / "docker-compose.yml"
    config = {
        "x-sentry-service-config": {
            "version": 0.2,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)
    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert str(e.value) == "Invalid version '0.2' in service config"


def test_load_service_config_from_file_missing_service_name(tmp_path: Path) -> None:
    devservices_dir = tmp_path / "devservices"
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = devservices_dir / "docker-compose.yml"
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert str(e.value) == "Service name is required in service config"


def test_load_service_config_from_file_invalid_dependency(tmp_path: Path) -> None:
    devservices_dir = tmp_path / "devservices"
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = devservices_dir / "docker-compose.yml"
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency", "unknown-dependency"]},
        }
    }
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)
    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert (
        str(e.value)
        == "Service 'unknown-dependency' in mode 'default' is not defined in dependencies"
    )
