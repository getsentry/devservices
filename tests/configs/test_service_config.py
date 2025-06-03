from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from devservices.configs.service_config import load_service_config_from_file
from devservices.configs.service_config import (
    load_supervisor_programs_from_programs_data,
)
from devservices.constants import DependencyType
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.utils.supervisor import ProgramData
from testing.utils import create_config_file


@pytest.mark.parametrize(
    "service_name, dependencies, modes, dependency_types",
    [
        (
            "example-service",
            {"example-dependency": {"description": "Example dependency"}},
            {"default": ["example-dependency"]},
            {
                "example-dependency": DependencyType.COMPOSE,
            },
        ),
        (
            "example-service",
            {
                "example-dependency-1": {
                    "description": "Example dependency 1",
                    "remote": {
                        "repo_name": "example-dependency-1",
                        "branch": "main",
                        "repo_link": "https://example.com",
                        "mode": "default",
                    },
                },
                "example-dependency-2": {
                    "description": "Example dependency 2",
                },
            },
            {"default": ["example-dependency-1", "example-dependency-2"]},
            {
                "example-dependency-1": DependencyType.SERVICE,
                "example-dependency-2": DependencyType.COMPOSE,
            },
        ),
        (
            "example-service",
            {
                "example-dependency-1": {
                    "description": "Example dependency 1",
                    "remote": {
                        "repo_name": "example-dependency-1",
                        "branch": "main",
                        "repo_link": "https://example.com",
                        "mode": "default",
                    },
                },
                "example-dependency-2": {
                    "description": "Example dependency 2",
                },
            },
            {"default": ["example-dependency-1"], "custom": ["example-dependency-2"]},
            {
                "example-dependency-1": DependencyType.SERVICE,
                "example-dependency-2": DependencyType.COMPOSE,
            },
        ),
    ],
)
def test_load_service_config_from_file(
    tmp_path: Path,
    service_name: str,
    dependencies: dict[str, dict[str, object]],
    modes: dict[str, list[str]],
    dependency_types: dict[str, DependencyType],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": service_name,
            "dependencies": {key: value for key, value in dependencies.items()},
            "modes": {key: value for key, value in modes.items()},
        },
        "services": {
            key: {
                "image": key,
            }
            for key in dependencies.keys()
        },
    }
    create_config_file(tmp_path, config)

    service_config = load_service_config_from_file(str(tmp_path))
    assert asdict(service_config) == {
        "version": 0.1,
        "service_name": service_name,
        "dependencies": {
            key: {
                "description": value["description"],
                "remote": value.get("remote"),
                "dependency_type": dependency_types[key],
            }
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
        },
        "services": {},
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
        == f"No devservices configuration found in {tmp_path / 'devservices' / 'config.yml'}"
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert str(e.value) == "Default mode is required in service config"


def test_load_service_config_from_file_remote_dependency_not_in_services(
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {
                    "description": "Example dependency",
                    "remote": {
                        "repo_name": "example-dependency",
                        "repo_link": "https://github.com/example/example-dependency",
                        "branch": "main",
                    },
                },
            },
            "modes": {"default": ["example-dependency"]},
        },
        "services": {},
    }
    create_config_file(tmp_path, config)

    load_service_config_from_file(str(tmp_path))


def test_load_service_config_from_file_no_matching_docker_compose_service(
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {
                    "description": "Example dependency",
                },
            },
            "modes": {"default": ["example-dependency"]},
        },
        "services": {},
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == "Dependency 'example-dependency' is not remote but is not defined in docker-compose services or x-programs"
    )


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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == "Unexpected key(s) in dependency 'example-dependency': {'unknown'}"
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
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
    tmp_file = Path(devservices_dir, "config.yml")
    with tmp_file.open("w") as f:
        f.write(config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == f"Error parsing config file: mapping values are not allowed here\n  in \"{tmp_path / 'devservices' / 'config.yml'}\", line 2, column 12"
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
    tmp_file = Path(devservices_dir, "config.yml")
    with tmp_file.open("w") as f:
        f.write(config)

    with pytest.raises(ConfigParseError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == f"Error parsing config file: could not determine a constructor for the tag 'tag:yaml.org,2002:invalid_tag'\n  in \"{tmp_path / 'devservices' / 'config.yml'}\", line 7, column 19"
    )


def test_load_service_config_from_file_no_programs_file(tmp_path: Path) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {
                    "description": "Example dependency",
                },
                "example-program": {
                    "description": "Example program",
                },
            },
            "modes": {"default": ["example-dependency", "example-program"]},
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
    }
    create_config_file(tmp_path, config)

    with pytest.raises(ConfigValidationError) as e:
        load_service_config_from_file(str(tmp_path))
    assert (
        str(e.value)
        == "Dependency 'example-program' is not remote but is not defined in docker-compose services or x-programs"
    )


def test_load_service_config_from_file_valid_programs_file(tmp_path: Path) -> None:
    devservices_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "example-dependency": {
                    "description": "Example dependency",
                },
                "example-program": {
                    "description": "Example program",
                },
            },
            "modes": {"default": ["example-dependency", "example-program"]},
        },
        "x-programs": {
            "example-program": {
                "command": "python run program",
                "autostart": True,
            }
        },
        "services": {
            "example-dependency": {
                "image": "example-dependency",
            }
        },
    }
    create_config_file(tmp_path, devservices_config)

    service_config = load_service_config_from_file(str(tmp_path))
    assert (
        service_config.dependencies["example-program"].dependency_type
        == DependencyType.SUPERVISOR
    )
    assert (
        service_config.dependencies["example-dependency"].dependency_type
        == DependencyType.COMPOSE
    )


def test_load_supervisor_programs_from_programs_data_no_x_programs(
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {},
            "modes": {"default": []},
        },
        "services": {},
    }
    create_config_file(tmp_path, config)
    config_path = tmp_path / "devservices" / "config.yml"

    programs = load_supervisor_programs_from_programs_data(
        str(config_path), "example-service", {}
    )
    assert programs == set()


def test_load_supervisor_programs_from_programs_data_with_x_programs(
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {},
            "modes": {"default": []},
        },
        "x-programs": {
            "example-program": {
                "command": "python run program",
                "autostart": True,
            }
        },
        "services": {},
    }
    create_config_file(tmp_path, config)
    config_path = tmp_path / "devservices" / "config.yml"

    programs = load_supervisor_programs_from_programs_data(
        str(config_path), "example-service", cast(ProgramData, config["x-programs"])
    )
    assert programs == {"example-program"}
