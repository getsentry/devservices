from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.logs import logs
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.services import Service
from devservices.utils.state import StateTables


@mock.patch("devservices.commands.logs.get_docker_compose_commands_to_run")
@mock.patch("devservices.commands.logs.find_matching_service")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_no_specified_service_not_running(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_get_docker_compose_commands_to_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
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
        mock_get_service_entries.return_value = []
        mock_find_matching_service.return_value = mock_service

        logs(args)

        mock_find_matching_service.assert_called_once_with(None)
        mock_get_service_entries.assert_has_calls(
            [
                mock.call(
                    StateTables.STARTING_SERVICES,
                ),
                mock.call(
                    StateTables.STARTED_SERVICES,
                ),
            ]
        )
        mock_install_and_verify_dependencies.assert_not_called()
        mock_get_docker_compose_commands_to_run.assert_not_called()

        captured = capsys.readouterr()
        assert "Service example-service is not running" in captured.out


# TODO: Ideally we should also have tests that don't mock the intermediate functions
@mock.patch("devservices.commands.logs.run_cmd")
@mock.patch("devservices.commands.logs.find_matching_service")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
@mock.patch("devservices.utils.docker_compose.get_non_remote_services")
def test_logs_no_specified_service_success(
    mock_get_non_remote_services: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_run_cmd: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
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
        mock_get_service_entries.return_value = ["example-service"]
        mock_find_matching_service.return_value = mock_service
        mock_get_non_remote_services.return_value = {"redis", "clickhouse"}
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                str(
                    tmp_path
                    / "example-service"
                    / DEVSERVICES_DIR_NAME
                    / CONFIG_FILE_NAME
                ),
                "logs",
                "clickhouse",
                "redis",
                "-n",
                "100",
            ],
            returncode=0,
            stdout="redis and clickhouse log output",
        )

        logs(args)

        mock_find_matching_service.assert_called_once_with(None)
        mock_get_service_entries.assert_has_calls(
            [
                mock.call(
                    StateTables.STARTING_SERVICES,
                ),
                mock.call(
                    StateTables.STARTED_SERVICES,
                ),
            ]
        )
        mock_install_and_verify_dependencies.assert_called_once()
        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                str(
                    tmp_path
                    / "example-service"
                    / DEVSERVICES_DIR_NAME
                    / CONFIG_FILE_NAME
                ),
                "logs",
                "clickhouse",
                "redis",
                "-n",
                "100",
            ],
            mock.ANY,
        )

        captured = capsys.readouterr()
        assert captured.out.endswith("redis and clickhouse log output\n")


def test_logs_no_config_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False)

    with pytest.raises(SystemExit):
        logs(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices logs sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )


@mock.patch("devservices.commands.logs.find_matching_service")
def test_logs_config_error(
    find_matching_service_mock: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    find_matching_service_mock.side_effect = ConfigError("Config error")
    args = Namespace(service_name="example-service")

    with pytest.raises(SystemExit):
        logs(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Config error" in captured.out.strip()


@mock.patch("devservices.commands.logs.find_matching_service")
def test_logs_service_not_found_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ServiceNotFoundError("Service not found")
    args = Namespace(service_name="example-service")

    with pytest.raises(SystemExit):
        logs(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()
