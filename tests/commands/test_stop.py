from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.stop import stop
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY
from testing.utils import create_config_file


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_stop_simple(mock_run: mock.Mock, tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.docker_compose.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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

        args = Namespace(service_name=None)

        stop(args)

        # Ensure the DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY is set and is relative
        env_vars = mock_run.call_args[1]["env"]
        assert env_vars[DEVSERVICES_LOCAL_DEPENDENCIES_DIR_KEY] == "../dependency-dir"

        mock_run.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "down",
                "redis",
                "clickhouse",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=mock.ANY,
        )


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_stop_error(
    mock_run: mock.Mock, capsys: pytest.CaptureFixture[str], tmp_path: Path
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

    args = Namespace(service_name=None)

    with pytest.raises(SystemExit):
        stop(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to stop example-service: Docker Compose error" in captured.out.strip()
    )
