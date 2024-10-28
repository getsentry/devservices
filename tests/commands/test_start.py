from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.start import start
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from testing.utils import create_config_file


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="clickhouse\nredis\n",
    ),
)
def test_start_simple(mock_run: mock.Mock, tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.docker_compose.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        start(args)

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


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_start_error(
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
        start(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to start example-service: Docker Compose error" in captured.out.strip()
    )
