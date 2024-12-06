from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.down import down
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.state import State
from testing.utils import create_config_file


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
@mock.patch("devservices.utils.state.State.remove_started_service")
def test_down_simple(
    mock_remove_started_service: mock.Mock,
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        args = Namespace(service_name=None, debug=False)

        with mock.patch(
            "devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")
        ):
            state = State()
            state.update_started_service("example-service", "default")
            down(args)

        # Ensure the DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY is set and is relative
        env_vars = mock_run.call_args[1]["env"]
        assert (
            env_vars[DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY]
            == f"../dependency-dir/{DEPENDENCY_CONFIG_VERSION}"
        )

        mock_run.assert_called_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "down",
                "clickhouse",
                "redis",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=mock.ANY,
        )

        mock_remove_started_service.assert_called_with("example-service")

        captured = capsys.readouterr()
        assert "Stopping clickhouse" in captured.out.strip()
        assert "Stopping redis" in captured.out.strip()


@mock.patch("devservices.utils.docker_compose.subprocess.run")
@mock.patch("devservices.utils.state.State.remove_started_service")
def test_down_error(
    mock_remove_started_service: mock.Mock,
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

    args = Namespace(service_name=None, debug=False)

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
        with pytest.raises(SystemExit):
            down(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to stop example-service: Docker Compose error" in captured.out.strip()
    )

    mock_remove_started_service.assert_not_called()

    captured = capsys.readouterr()
    assert "Stopping clickhouse" not in captured.out.strip()
    assert "Stopping redis" not in captured.out.strip()


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
@mock.patch("devservices.utils.state.State.remove_started_service")
def test_down_mode_simple(
    mock_remove_started_service: mock.Mock,
    mock_run: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        args = Namespace(service_name=None, debug=False)

        with mock.patch(
            "devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")
        ):
            state = State()
            state.update_started_service("example-service", "test")
            down(args)

        # Ensure the DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY is set and is relative
        env_vars = mock_run.call_args[1]["env"]
        assert (
            env_vars[DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY]
            == f"../dependency-dir/{DEPENDENCY_CONFIG_VERSION}"
        )

        mock_run.assert_called_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "down",
                "redis",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=mock.ANY,
        )

        mock_remove_started_service.assert_called_with("example-service")

        captured = capsys.readouterr()
        assert "Stopping redis" in captured.out.strip()


@mock.patch("devservices.commands.down.find_matching_service")
def test_down_config_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ConfigError("Config error")
    args = Namespace(service_name="example-service", debug=False)

    with pytest.raises(SystemExit):
        down(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Config error" in captured.out.strip()


@mock.patch("devservices.commands.down.find_matching_service")
def test_down_service_not_found_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ServiceNotFoundError("Service not found")
    args = Namespace(service_name="example-service", debug=False)

    with pytest.raises(SystemExit):
        down(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()
