from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from devservices.configs.service_config import load_service_config_from_file
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from tests.testutils import create_config_file


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
            {"default": ["example-dependency-1"], "custom": ["example-dependency-2"]},
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

    service_config = load_service_config_from_file(str(tmp_path))
    assert asdict(service_config) == {
        "version": 0.1,
        "service_name": service_name,
        "dependencies": {
            key: {"description": value["description"], "link": value.get("link")}
            for key, value in dependencies.items()
        },
        "modes": modes,
    }


def test_load_service_config_from_file_no_dependencies(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "modes": {"default": []},
        }
    }
    create_config_file(tmp_path, config)

    service_config = load_service_config_from_file(str(tmp_path))
    assert asdict(service_config) == {
        "version": 0.1,
        "service_name": "example-service",
        "dependencies": {},
        "modes": {"default": []},
    }


def test_load_service_config_from_file_missing_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigNotFoundError) as e:
        load_service_config_from_file(str(tmp_path))
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
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Invalid version '0.2' in service config"


def test_load_service_config_from_file_missing_version(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Version is required in service config"


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
        load_service_config_from_file(str(tmp_path))
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
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == "Service 'unknown-dependency' in mode 'default' is not defined in dependencies"
    )


def test_load_service_config_from_file_missing_default_mode(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"custom": ["example-dependency"]},
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Default mode is required in service config"


def test_load_service_config_from_file_no_modes(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Default mode is required in service config"


def test_load_service_config_from_file_invalid_dependencies(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {
                    "description": "Example dependency",
                    "unknown": "key",
                }
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == "Error parsing service dependencies: Dependency.__init__() got an unexpected keyword argument 'unknown'"
    )


def test_load_service_config_from_file_invalid_modes(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {
                "default": ["example-dependency"],
                "custom": "example-dependency",
            },
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Services in mode 'custom' must be a list"


def test_load_service_config_from_file_no_x_sentry_service_config(
    tmp_path: Path,
) -> None:
    config = {
        "x-not-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {"description": "Example dependency"}
            },
            "modes": {"default": ["example-dependency"]},
        }
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Config file does not contain 'x-sentry-service-config' key"


def test_load_service_config_from_file_invalid_yaml(tmp_path: Path) -> None:
    config = """x-sentry-service-config
    version: 0.1
    service_name: "example-service"
    dependencies:
        example-dependency:
            description: "Example dependency"
    modes:
        default: ["example-dependency"]"""
    devservices_dir = Path(tmp_path, "devservices")
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, "docker-compose.yml")
    with tmp_file.open("w") as f:
        f.write(config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == f"Error parsing config file: mapping values are not allowed here\n  in \"{tmp_path / 'devservices' / 'docker-compose.yml'}\", line 2, column 12"
    )


def test_load_service_config_from_file_invalid_yaml_tag(tmp_path: Path) -> None:
    config = """x-sentry-service-config:
    version: 0.1
    service_name: "example-service"
    dependencies:
        example-dependency:
            description: "Example dependency"
            link: !!invalid_tag "https://example.com"
    modes:
        default: ["example-dependency"]"""
    devservices_dir = Path(tmp_path, "devservices")
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, "docker-compose.yml")
    with tmp_file.open("w") as f:
        f.write(config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == f"Error parsing config file: could not determine a constructor for the tag 'tag:yaml.org,2002:invalid_tag'\n  in \"{tmp_path / 'devservices' / 'docker-compose.yml'}\", line 7, column 19"
    )
