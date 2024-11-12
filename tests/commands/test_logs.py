from __future__ import annotations

import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.logs import logs
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import ServiceConfig
from devservices.utils.services import Service


@mock.patch("devservices.commands.logs.run_docker_compose_command")
@mock.patch("devservices.commands.logs.find_matching_service")
@mock.patch("devservices.utils.state.State.get_started_services")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_no_specified_service_not_running(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_started_services: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_run_docker_compose_command: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = Namespace(service_name=None)
    mock_service = Service(
        name="example-service",
        config=ServiceConfig(
            version=0.1,
            service_name="example-service",
            dependencies={
                "redis": Dependency(description="Redis"),
                "clickhouse": Dependency(description="Clickhouse"),
            },
            modes={"default": ["redis", "clickhouse"]},
        ),
        repo_path=str(tmp_path / "example-service"),
    )
    mock_get_started_services.return_value = []
    mock_find_matching_service.return_value = mock_service

    logs(args)

    mock_find_matching_service.assert_called_once_with(None)
    mock_get_started_services.assert_called_once()
    mock_install_and_verify_dependencies.assert_not_called()
    mock_run_docker_compose_command.assert_not_called()

    captured = capsys.readouterr()
    assert "Service example-service is not running" in captured.out


@mock.patch("devservices.commands.logs.run_docker_compose_command")
@mock.patch("devservices.commands.logs.find_matching_service")
@mock.patch("devservices.utils.state.State.get_started_services")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_no_specified_service_success(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_started_services: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_run_docker_compose_command: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = Namespace(service_name=None)
    mock_service = Service(
        name="example-service",
        config=ServiceConfig(
            version=0.1,
            service_name="example-service",
            dependencies={
                "redis": Dependency(description="Redis"),
                "clickhouse": Dependency(description="Clickhouse"),
            },
            modes={"default": ["redis", "clickhouse"]},
        ),
        repo_path=str(tmp_path / "example-service"),
    )
    mock_install_and_verify_dependencies.return_value = {}
    mock_get_started_services.return_value = ["example-service"]
    mock_find_matching_service.return_value = mock_service
    mock_run_docker_compose_command.return_value = [
        subprocess.CompletedProcess(
            args=["docker", "compose", "logs", "redis", "clickhouse"],
            returncode=0,
            stdout="redis and clickhouse log output",
        )
    ]

    logs(args)

    mock_find_matching_service.assert_called_once_with(None)
    mock_get_started_services.assert_called_once()
    mock_install_and_verify_dependencies.assert_called_once()
    mock_run_docker_compose_command.assert_called_once_with(
        mock_service,
        "logs",
        ["redis", "clickhouse"],
        {},
        options=["-n", "100"],
    )

    captured = capsys.readouterr()
    assert captured.out.endswith("redis and clickhouse log output\n")
