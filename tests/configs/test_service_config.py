from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
import yaml
from configs.service_config import load_service_config_from_file
from exceptions import ConfigNotFoundError
from exceptions import ConfigValidationError


def create_config_file(tmp_path: Path, config: dict[str, dict[str, object]]) -> None:
    devservices_dir = Path(tmp_path, "devservices")
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, "docker-compose.yml")
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)


@pytest.mark.parametrize(
    "service_name, dependencies, modes",
    [
        (
            "example-service",
            {"example-dependency": {"description": "Example dependency"}},
            {"default": ["example-dependency"]},
        ),
        (
            "example-service",
            {
                "example-dependency-1": {
                    "description": "Example dependency 1",
                    "link": "https://example.com",
                },
                "example-dependency-2": {
                    "description": "Example dependency 2",
                },
            },
            {"default": ["example-dependency-1", "example-dependency-2"]},
        ),
    ],
)
def test_load_service_config_from_file(
    tmp_path: Path,
    service_name: str,
    dependencies: dict[str, dict[str, object]],
    modes: dict[str, list[str]],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": service_name,
            "dependencies": {key: value for key, value in dependencies.items()},
            "modes": {key: value for key, value in modes.items()},
        }
    }
    create_config_file(tmp_path, config)

    service_config = load_service_config_from_file(tmp_path)
    assert asdict(service_config) == {
        "version": 0.1,
        "service_name": service_name,
        "dependencies": {
            key: {"description": value["description"], "link": value.get("link")}
            for key, value in dependencies.items()
        },
        "modes": modes,
    }


def test_load_service_config_from_file_missing_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigNotFoundError) as e:
        load_service_config_from_file(tmp_path)
    assert (
        str(e.value)
        == f"Config file not found in directory: {tmp_path / 'devservices' / 'docker-compose.yml'}"
    )


def test_load_service_config_from_file_invalid_version(tmp_path: Path) -> None:
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
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert str(e.value) == "Invalid version '0.2' in service config"


def test_load_service_config_from_file_missing_service_name(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert str(e.value) == "Service name is required in service config"


def test_load_service_config_from_file_invalid_dependency(tmp_path: Path) -> None:
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
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(tmp_path)
    assert (
        str(e.value)
        == "Service 'unknown-dependency' in mode 'default' is not defined in dependencies"
    )
