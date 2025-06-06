from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.logs import _supervisor_logs
from devservices.commands.logs import logs
from devservices.configs.service_config import load_service_config_from_file
from devservices.constants import Color
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import SupervisorError
from devservices.utils.services import Service
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo


@mock.patch("devservices.commands.logs.get_docker_compose_commands_to_run")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_no_specified_service_not_running(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_get_docker_compose_commands_to_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            str(tmp_path / "code"),
        ),
    ):
        # Create a test service
        test_service_repo_path = tmp_path / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
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
        create_config_file(test_service_repo_path, config)

        # Change to the service directory and run logs
        os.chdir(test_service_repo_path)
        args = Namespace(service_name=None)
        mock_get_service_entries.return_value = []

        logs(args)

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
        assert (
            f"{Color.YELLOW}Service test-service is not running{Color.RESET}\n"
            == captured.out
        )


@mock.patch("devservices.commands.logs.run_cmd")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
@mock.patch("devservices.utils.docker_compose.get_non_remote_services")
def test_logs_no_specified_service_success(
    mock_get_non_remote_services: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_run_cmd: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            str(tmp_path / "code"),
        ),
    ):
        # Create a test service
        test_service_repo_path = tmp_path / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
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
        create_config_file(test_service_repo_path, config)

        # Change to the service directory and run logs
        os.chdir(test_service_repo_path)
        args = Namespace(service_name=None)
        mock_install_and_verify_dependencies.return_value = set()
        mock_get_service_entries.return_value = ["test-service"]
        mock_get_non_remote_services.return_value = {"redis", "clickhouse"}
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[
                "docker",
                "compose",
                "-p",
                "test-service",
                "-f",
                str(test_service_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME),
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
                "test-service",
                "-f",
                str(test_service_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME),
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


def test_logs_config_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.utils.services.get_coderoot",
        return_value=str(tmp_path / "code"),
    ):
        # Create an invalid config file
        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("invalid_repo", test_service_repo_path)

        args = Namespace(service_name="test-service")

        with pytest.raises(SystemExit):
            logs(args)

        captured = capsys.readouterr()
        assert "test-service was found with an invalid config" in captured.out


def test_logs_service_not_found_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with mock.patch(
        "devservices.utils.services.get_coderoot",
        return_value=str(tmp_path / "code"),
    ):
        # Create empty code directory
        os.makedirs(tmp_path / "code", exist_ok=True)

        args = Namespace(service_name="nonexistent-service")

        with pytest.raises(SystemExit):
            logs(args)

        captured = capsys.readouterr()
        assert (
            f"{Color.RED}Service 'nonexistent-service' not found.{Color.RESET}"
            == captured.out.strip()
        )


@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_dependency_error(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        # Create a test service
        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(test_service_repo_path, config)

        args = Namespace(service_name="test-service")
        mock_get_service_entries.return_value = ["test-service"]
        mock_install_and_verify_dependencies.side_effect = DependencyError(
            repo_name="test-service",
            repo_link=str(tmp_path),
            branch="main",
            stderr="Dependency installation failed",
        )

        with pytest.raises(SystemExit):
            logs(args)

        captured = capsys.readouterr()
        assert (
            f"{Color.RED}DependencyError: test-service ({tmp_path}) on main. If this error persists, try running `devservices purge`{Color.RESET}\n"
            == captured.out
        )


@mock.patch("devservices.commands.logs._logs")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_docker_compose_error(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_logs: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        # Create a test service
        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(test_service_repo_path, config)

        args = Namespace(service_name="test-service")
        mock_get_service_entries.return_value = ["test-service"]
        mock_install_and_verify_dependencies.return_value = set()
        mock_logs.side_effect = DockerComposeError(
            command="docker compose logs",
            returncode=1,
            stdout="",
            stderr="stderr_output",
        )

        with pytest.raises(SystemExit):
            logs(args)

        captured = capsys.readouterr()
        assert (
            f"{Color.RED}Failed to get logs for test-service: stderr_output{Color.RESET}\n"
            == captured.out
        )


@mock.patch("devservices.commands.logs._supervisor_logs")
@mock.patch("devservices.commands.logs._logs")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
def test_logs_with_supervisor_dependencies(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_logs: mock.Mock,
    mock_supervisor_logs: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        # Create a test service with supervisor dependencies
        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis", "dependency_type": "compose"},
                    "worker": {
                        "description": "Worker",
                        "dependency_type": "supervisor",
                    },
                },
                "modes": {"default": ["redis", "worker"]},
            },
            "x-programs": {
                "worker": {
                    "command": "python run worker",
                },
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(test_service_repo_path, config)

        args = Namespace(service_name="test-service")
        mock_get_service_entries.return_value = ["test-service"]
        mock_install_and_verify_dependencies.return_value = set()
        mock_logs.return_value = [
            subprocess.CompletedProcess(
                args=["docker", "compose", "logs"],
                returncode=0,
                stdout="docker logs output",
            )
        ]
        mock_supervisor_logs.return_value = {"worker": "supervisor worker logs output"}

        logs(args)

        # Verify that supervisor logs were called with the right service
        mock_supervisor_logs.assert_called_once()
        supervisor_call_args = mock_supervisor_logs.call_args[0]
        assert supervisor_call_args[0].name == "test-service"
        assert supervisor_call_args[1] == ["worker"]

        captured = capsys.readouterr()
        assert (
            "docker logs output\n=== Logs for supervisor program: worker ===\nsupervisor worker logs output\n"
            == captured.out
        )


@mock.patch("devservices.commands.logs.SupervisorManager")
def test_supervisor_logs_no_config_file(
    mock_supervisor_manager_class: mock.Mock,
    tmp_path: Path,
) -> None:
    test_service_repo_path = tmp_path / "test-service"
    create_mock_git_repo("blank_repo", test_service_repo_path)
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
            "dependencies": {
                "worker": {"description": "Worker", "dependency_type": "supervisor"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python run worker",
            },
        },
    }
    create_config_file(test_service_repo_path, config)

    service_config = load_service_config_from_file(str(test_service_repo_path))
    service = Service(
        name=service_config.service_name,
        repo_path=str(test_service_repo_path),
        config=service_config,
    )

    # Mock SupervisorManager to raise an exception when config file doesn't exist
    mock_supervisor_manager_class.side_effect = Exception("Config file not found")

    # The current implementation doesn't handle general exceptions during manager creation
    # so this will raise an exception
    with pytest.raises(Exception, match="Config file not found"):
        _supervisor_logs(service, ["worker"])


@mock.patch("devservices.commands.logs.SupervisorManager")
def test_supervisor_logs_manager_creation_error(
    mock_supervisor_manager_class: mock.Mock,
    tmp_path: Path,
) -> None:
    # Create a test service
    test_service_repo_path = tmp_path / "test-service"
    create_mock_git_repo("blank_repo", test_service_repo_path)
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
            "dependencies": {
                "worker": {"description": "Worker", "dependency_type": "supervisor"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python run worker",
            },
        },
    }
    create_config_file(test_service_repo_path, config)

    # Load the service from config
    from devservices.configs.service_config import load_service_config_from_file

    service_config = load_service_config_from_file(str(test_service_repo_path))
    service = Service(
        name=service_config.service_name,
        repo_path=str(test_service_repo_path),
        config=service_config,
    )

    # Mock SupervisorManager to raise an exception during creation
    mock_supervisor_manager_class.side_effect = Exception("General supervisor error")

    # The current implementation doesn't handle general exceptions during manager creation
    # so this will raise an exception
    with pytest.raises(Exception, match="General supervisor error"):
        _supervisor_logs(service, ["worker"])


def test_supervisor_logs_empty_programs_list(tmp_path: Path) -> None:
    # Create a test service
    test_service_repo_path = tmp_path / "test-service"
    create_mock_git_repo("blank_repo", test_service_repo_path)
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
            "dependencies": {},
            "modes": {"default": []},
        },
    }
    create_config_file(test_service_repo_path, config)

    # Load the service from config
    from devservices.configs.service_config import load_service_config_from_file

    service_config = load_service_config_from_file(str(test_service_repo_path))
    service = Service(
        name=service_config.service_name,
        repo_path=str(test_service_repo_path),
        config=service_config,
    )

    result = _supervisor_logs(service, [])

    assert result == {}


@mock.patch("devservices.utils.state.State.get_active_modes_for_service")
@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.commands.logs.install_and_verify_dependencies")
@mock.patch("devservices.commands.logs._logs")
def test_logs_with_active_modes(
    mock_logs: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    mock_get_service_entries: mock.Mock,
    mock_get_active_modes: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.logs.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        # Create a test service with multiple modes
        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "postgres": {"description": "Postgres"},
                },
                "modes": {
                    "default": ["redis"],
                    "full": ["redis", "postgres"],
                },
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "postgres": {"image": "postgres:13"},
            },
        }
        create_config_file(test_service_repo_path, config)

        args = Namespace(service_name="test-service")
        mock_get_service_entries.return_value = ["test-service"]
        mock_get_active_modes.side_effect = [
            ["full"],  # starting modes
            [],  # started modes
        ]
        mock_install_and_verify_dependencies.return_value = set()
        mock_logs.return_value = []

        logs(args)

        mock_install_and_verify_dependencies.assert_called_once()
        call_args = mock_install_and_verify_dependencies.call_args[0]
        assert call_args[0].name == "test-service"
        assert call_args[0].config.modes["full"] == ["redis", "postgres"]


@mock.patch("devservices.commands.logs.SupervisorManager")
def test_supervisor_logs_success(
    mock_supervisor_manager_class: mock.Mock,
    tmp_path: Path,
) -> None:
    test_service_repo_path = tmp_path / "test-service"
    create_mock_git_repo("blank_repo", test_service_repo_path)
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
            "dependencies": {
                "worker": {"description": "Worker", "dependency_type": "supervisor"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python run worker",
            },
        },
    }
    create_config_file(test_service_repo_path, config)

    # Create the programs.conf file
    config_file_path = test_service_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME

    # Load the service from config
    from devservices.configs.service_config import load_service_config_from_file

    service_config = load_service_config_from_file(str(test_service_repo_path))
    service = Service(
        name=service_config.service_name,
        repo_path=str(test_service_repo_path),
        config=service_config,
    )

    mock_manager = mock.Mock()
    mock_manager.get_program_logs.return_value = "worker program logs"
    mock_supervisor_manager_class.return_value = mock_manager

    result = _supervisor_logs(service, ["worker"])

    assert result == {"worker": "worker program logs"}
    mock_supervisor_manager_class.assert_called_once_with(
        "test-service", str(config_file_path)
    )
    mock_manager.get_program_logs.assert_called_once_with("worker")


@mock.patch("devservices.commands.logs.SupervisorManager")
def test_supervisor_logs_supervisor_error(
    mock_supervisor_manager_class: mock.Mock,
    tmp_path: Path,
) -> None:
    """Test _supervisor_logs function when supervisor raises an error."""
    # Create a test service
    test_service_repo_path = tmp_path / "test-service"
    create_mock_git_repo("blank_repo", test_service_repo_path)
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
            "dependencies": {
                "worker": {"description": "Worker", "dependency_type": "supervisor"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python run worker",
            },
        },
    }
    create_config_file(test_service_repo_path, config)

    # Create the programs.conf file
    config_file_path = test_service_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME

    # Load the service from config
    from devservices.configs.service_config import load_service_config_from_file

    service_config = load_service_config_from_file(str(test_service_repo_path))
    service = Service(
        name=service_config.service_name,
        repo_path=str(test_service_repo_path),
        config=service_config,
    )

    mock_manager = mock.Mock()
    mock_manager.get_program_logs.side_effect = SupervisorError("Failed to get logs")
    mock_supervisor_manager_class.return_value = mock_manager

    result = _supervisor_logs(service, ["worker"])

    assert result == {"worker": "Error getting logs for worker: Failed to get logs"}
    mock_supervisor_manager_class.assert_called_once_with(
        "test-service", str(config_file_path)
    )
    mock_manager.get_program_logs.assert_called_once_with("worker")
