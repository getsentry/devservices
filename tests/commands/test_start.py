from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path

import mock
import pytest
from commands.start import start
from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from utils.docker_compose import run_docker_compose_command

from tests.utils import create_config_file


def test_start_simple(tmp_path: Path) -> None:
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
    start(args)

    # Check to make sure services are running
    docker_compose_ps_output = run_docker_compose_command(
        f"-f {tmp_path}/{DEVSERVICES_DIR_NAME}/{DOCKER_COMPOSE_FILE_NAME} ps --services"
    ).stdout
    assert (
        docker_compose_ps_output
        == """clickhouse
redis
"""
    )

    run_docker_compose_command(
        f"-f {tmp_path}/{DEVSERVICES_DIR_NAME}/{DOCKER_COMPOSE_FILE_NAME} down"
    )


@mock.patch("utils.docker_compose.subprocess.run")
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
        captured.out.strip() == "Failed to start example-service: Docker Compose error"
    )
