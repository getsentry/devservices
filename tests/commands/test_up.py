from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.up import up
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import DependencyError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.state import State
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
@mock.patch("devservices.utils.state.State.update_started_service")
@mock.patch("devservices.commands.up._create_devservices_network")
def test_up_simple(
    mock_create_devservices_network: mock.Mock,
    mock_update_started_service: mock.Mock,
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(service_name=None, debug=False, mode="default")

        up(args)

        # Ensure the DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY is set and is relative
        env_vars = mock_run.call_args[1]["env"]
        assert (
            env_vars[DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY]
            == f"../dependency-dir/{DEPENDENCY_CONFIG_VERSION}"
        )

        mock_create_devservices_network.assert_called_once()

        mock_run.assert_called_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "clickhouse",
                "redis",
                "-d",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=mock.ANY,
        )

        mock_update_started_service.assert_called_with("example-service", "default")
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'default'" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


@mock.patch("devservices.utils.docker_compose.subprocess.run")
@mock.patch("devservices.utils.state.State.update_started_service")
@mock.patch("devservices.commands.up._create_devservices_network")
def test_up_dependency_error(
    mock_create_devservices_network: mock.Mock,
    mock_update_started_service: mock.Mock,
    mock_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.commands.up.install_and_verify_dependencies",
    ) as mock_install_and_verify_dependencies:
        mock_install_and_verify_dependencies.side_effect = DependencyError(
            "example-repo", "link", "branch"
        )
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        create_config_file(tmp_path, config)
        os.chdir(tmp_path)

        args = Namespace(service_name=None, debug=False, mode="default")

        with pytest.raises(SystemExit):
            up(args)

        mock_create_devservices_network.assert_not_called()
        # Capture the printed output
        captured = capsys.readouterr()

        assert "DependencyError: example-repo (link) on branch" in captured.out.strip()

        mock_update_started_service.assert_not_called()

        captured = capsys.readouterr()
        assert "Retrieving dependencies" not in captured.out.strip()
        assert (
            "Starting 'example-service' in mode: 'default'" not in captured.out.strip()
        )
        assert "Starting clickhouse" not in captured.out.strip()
        assert "Starting redis" not in captured.out.strip()


@mock.patch("devservices.utils.docker_compose.subprocess.run")
@mock.patch("devservices.utils.state.State.update_started_service")
@mock.patch("devservices.commands.up._create_devservices_network")
def test_up_error(
    mock_create_devservices_network: mock.Mock,
    mock_update_started_service: mock.Mock,
    mock_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, stderr="Docker Compose error", cmd=""
    )
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "clickhouse": {"description": "Clickhouse"},
            },
            "modes": {"default": ["redis", "clickhouse"]},
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
            "clickhouse": {
                "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
            },
        },
    }

    create_config_file(tmp_path, config)
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False, mode="default")

    with pytest.raises(SystemExit):
        up(args)

    mock_create_devservices_network.assert_called_once()

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to start example-service: Docker Compose error" in captured.out.strip()
    )

    mock_update_started_service.assert_not_called()

    captured = capsys.readouterr()
    assert "Retrieving dependencies" not in captured.out.strip()
    assert "Starting 'example-service' in mode: 'default'" not in captured.out.strip()
    assert "Starting clickhouse" not in captured.out.strip()
    assert "Starting redis" not in captured.out.strip()


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
@mock.patch("devservices.utils.state.State.update_started_service")
@mock.patch("devservices.commands.up._create_devservices_network")
def test_up_mode_simple(
    mock_create_devservices_network: mock.Mock,
    mock_update_started_service: mock.Mock,
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(service_name=None, debug=False, mode="test")

        up(args)

        # Ensure the DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY is set and is relative
        env_vars = mock_run.call_args[1]["env"]
        assert (
            env_vars[DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY]
            == f"../dependency-dir/{DEPENDENCY_CONFIG_VERSION}"
        )

        mock_create_devservices_network.assert_called_once()

        mock_run.assert_called_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "redis",
                "-d",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=mock.ANY,
        )

        mock_update_started_service.assert_called_with("example-service", "test")
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
@mock.patch("devservices.utils.state.State.update_started_service")
def test_up_mode_does_not_exist(
    mock_update_started_service: mock.Mock,
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(service_name=None, debug=False, mode="test")

        with pytest.raises(SystemExit):
            up(args)

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            "ModeDoesNotExistError: Mode 'test' does not exist for service 'example-service'"
            in captured.out.strip()
        )

        mock_update_started_service.assert_not_called()

        captured = capsys.readouterr()
        assert "Retrieving dependencies" not in captured.out.strip()
        assert "Starting 'example-service' in mode: 'test'" not in captured.out.strip()
        assert "Starting clickhouse" not in captured.out.strip()
        assert "Starting redis" not in captured.out.strip()


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
def test_up_mutliple_modes(
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        state = State()
        state.update_started_service("example-service", "default")

        args = Namespace(service_name=None, debug=False, mode="test")
        up(args)

        mock_run.assert_has_calls(
            [
                mock.call(
                    [
                        "docker",
                        "compose",
                        "-p",
                        "example-service",
                        "-f",
                        f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "up",
                        "redis",
                        "-d",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=mock.ANY,
                ),
            ],
            any_order=True,
        )

        captured = capsys.readouterr()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


def test_up_multiple_modes_overlapping_running_service(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        redis_repo_path = tmp_path / "redis"
        create_mock_git_repo("blank_repo", redis_repo_path)
        mock_git_repo_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "shared-redis",
                "dependencies": {},
                "modes": {"default": []},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(redis_repo_path, mock_git_repo_config)
        run_git_command(["add", "."], cwd=redis_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=redis_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["redis"]},
            },
        }

        service_path = tmp_path / "code" / "example-service"
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(service_path, config)
        create_config_file(other_service_path, other_config)
        os.chdir(service_path)

        state = State()
        state.update_started_service("example-service", "default")
        state.update_started_service("other-service", "default")

        args = Namespace(service_name="example-service", debug=False, mode="test")

        with mock.patch(
            "devservices.commands.up.run_cmd",
            return_value=subprocess.CompletedProcess(
                args=["docker", "compose", "config", "--services"],
                returncode=0,
                stdout="clickhouse\n",
            ),
        ) as mock_run:
            up(args)

            mock_run.assert_has_calls(
                [
                    mock.call(
                        [
                            "docker",
                            "compose",
                            "-p",
                            "example-service",
                            "-f",
                            f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            "up",
                            "clickhouse",
                            "-d",
                        ],
                        mock.ANY,
                    ),
                ],
            )

        captured = capsys.readouterr()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()


@mock.patch("devservices.commands.up.find_matching_service")
def test_up_config_error(
    find_matching_service_mock: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    find_matching_service_mock.side_effect = ConfigError("Config error")
    args = Namespace(service_name="example-service", debug=False, mode="test")

    with pytest.raises(SystemExit):
        up(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Config error" in captured.out.strip()


@mock.patch("devservices.commands.up.find_matching_service")
def test_up_service_not_found_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ServiceNotFoundError("Service not found")
    args = Namespace(service_name="example-service", debug=False, mode="test")

    with pytest.raises(SystemExit):
        up(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()
