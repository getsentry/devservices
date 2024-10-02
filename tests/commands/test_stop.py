from __future__ import annotations

import os
import subprocess
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.stop import stop
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from testing.utils import create_config_file


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_stop_simple(mock_run: mock.Mock, tmp_path: Path) -> None:
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

    with tempfile.NamedTemporaryFile(delete=False) as temp_env_file:
        temp_env_file_path = temp_env_file.name

    try:
        with mock.patch("tempfile.NamedTemporaryFile") as mock_tempfile:
            mock_tempfile.return_value.__enter__.return_value.name = temp_env_file_path

            stop(args)

            mock_run.assert_called_once_with(
                [
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{tmp_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "--env-file",
                    temp_env_file_path,
                    "down",
                    "redis",
                    "clickhouse",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
    finally:
        # Ensure the temporary file is removed (even if the test fails)
        if os.path.exists(temp_env_file_path):
            os.remove(temp_env_file_path)
            assert False, f"Failed to remove temporary file {temp_env_file_path}"


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

    with tempfile.NamedTemporaryFile(delete=False) as temp_env_file:
        temp_env_file_path = temp_env_file.name

    try:
        with mock.patch("tempfile.NamedTemporaryFile") as mock_tempfile:
            mock_tempfile.return_value.__enter__.return_value.name = temp_env_file_path

            with pytest.raises(SystemExit):
                stop(args)

            # Capture the printed output
            captured = capsys.readouterr()

            assert (
                "Failed to stop example-service: Docker Compose error"
                in captured.out.strip()
            )
    finally:
        # Ensure the temporary file is removed (even if the test fails)
        if os.path.exists(temp_env_file_path):
            os.remove(temp_env_file_path)
            assert False, f"Failed to remove temporary file {temp_env_file_path}"
