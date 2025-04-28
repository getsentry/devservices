from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from devservices.commands.serve import serve
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import PROGRAMS_CONF_FILE_NAME
from testing.utils import create_config_file
from testing.utils import create_programs_conf_file


@patch("devservices.commands.serve.pty.spawn")
def test_serve_success(
    mock_pty_spawn: Mock,
    tmp_path: Path,
) -> None:
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
    programs_config = """
[program:devserver]
command=run devserver
autostart=true
autorestart=true
"""
    create_programs_conf_file(service_path, programs_config)

    args = Namespace(extra=[])

    serve(args)

    mock_pty_spawn.assert_called_once_with(["run", "devserver"])


@patch("devservices.commands.serve.pty.spawn")
def test_serve_devservices_config_not_found(
    mock_pty_spawn: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    args = Namespace(extra=[])

    serve(args)

    out, err = capsys.readouterr()
    assert (
        out
        == f"\x1b[0;31mNo programs.conf file found in {service_path}/{DEVSERVICES_DIR_NAME}/{PROGRAMS_CONF_FILE_NAME}.\x1b[0m\n"
    )
    mock_pty_spawn.assert_not_called()


@patch("devservices.commands.serve.pty.spawn")
def test_serve_programs_conf_not_found(
    mock_pty_spawn: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service_path = tmp_path / "example-service"
    os.makedirs(service_path)
    os.chdir(service_path)

    args = Namespace(extra=[])

    serve(args)

    out, err = capsys.readouterr()
    assert (
        out
        == f"\x1b[0;31mNo devservices configuration found in {service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}. Please run the command from a directory with a valid devservices configuration.\x1b[0m\n"
    )
    mock_pty_spawn.assert_not_called()


@patch("devservices.commands.serve.pty.spawn")
def test_serve_devserver_command_not_found(
    mock_pty_spawn: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    programs_config = """
[program:consumer]
command=run consumer
autostart=true
autorestart=true
"""
    create_programs_conf_file(service_path, programs_config)

    args = Namespace(extra=[])

    serve(args)

    out, err = capsys.readouterr()
    assert (
        out
        == "\x1b[0;31mError when getting devserver command: Program devserver not found in config\x1b[0m\n"
    )
    mock_pty_spawn.assert_not_called()
