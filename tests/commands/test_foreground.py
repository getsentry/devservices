from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.foreground import foreground
from devservices.constants import Color
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ServiceNotFoundError
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_success(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["redis", "worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    mock_stop_process.assert_called_once_with("worker")
    mock_pty_spawn.assert_called_once_with(["python", "worker.py"])
    mock_start_process.assert_called_once_with("worker")


@mock.patch("devservices.commands.foreground.pty.spawn")
def test_foreground_service_not_running(
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"{Color.YELLOW}example-service is not running{Color.RESET}\n" == captured.out
    )

    mock_pty_spawn.assert_not_called()


@mock.patch("devservices.commands.foreground.pty.spawn")
def test_foreground_program_not_in_supervisor_programs(
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["redis", "worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="nonexistent")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"{Color.RED}Program nonexistent does not exist in the service's config{Color.RESET}\n"
        == captured.out
    )

    mock_pty_spawn.assert_not_called()


@mock.patch("devservices.commands.foreground.pty.spawn")
def test_foreground_program_not_in_active_modes(
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["redis"], "other": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"{Color.RED}Program worker is not running in any active modes of example-service{Color.RESET}\n"
        == captured.out
    )

    mock_pty_spawn.assert_not_called()


@mock.patch("devservices.commands.foreground.pty.spawn")
def test_foreground_programs_conf_not_found(
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["redis", "worker"]},
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        pytest.raises(SystemExit),
    ):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"{Color.RED}Dependency 'worker' is not remote but is not defined in docker-compose services or x-programs{Color.RESET}\n"
        == captured.out
    )

    mock_pty_spawn.assert_not_called()


def test_foreground_config_not_found_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(program_name="worker")

    with pytest.raises(SystemExit):
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"{Color.RED}No devservices configuration found in {tmp_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME}. Please specify a service (i.e. `devservices down sentry`) or run the command from a directory with a devservices configuration.{Color.RESET}\n"
        == captured.out
    )


@mock.patch("devservices.commands.foreground.find_matching_service")
def test_foreground_config_error(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_find_matching_service.side_effect = ConfigError("Invalid config")

    args = Namespace(program_name="worker")

    with pytest.raises(SystemExit):
        foreground(args)

    captured = capsys.readouterr()
    assert f"{Color.RED}Invalid config{Color.RESET}\n" == captured.out


@mock.patch("devservices.commands.foreground.find_matching_service")
def test_foreground_service_not_found_error(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_find_matching_service.side_effect = ServiceNotFoundError("Service not found")

    args = Namespace(program_name="worker")

    with pytest.raises(SystemExit):
        foreground(args)

    captured = capsys.readouterr()
    assert f"{Color.RED}Service not found{Color.RESET}\n" == captured.out


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.get_program_command")
def test_foreground_supervisor_config_error(
    mock_get_program_command: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    mock_get_program_command.side_effect = SupervisorConfigError("Program config error")

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    # Verify output
    captured = capsys.readouterr()
    assert (
        f"{Color.RED}Error when getting program command: Program config error{Color.RESET}\n"
        == captured.out
    )

    # Verify pty.spawn was not called
    mock_pty_spawn.assert_not_called()


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_pty_spawn_exception(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    mock_pty_spawn.side_effect = OSError("Spawn failed")

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    captured = capsys.readouterr()
    assert (
        f"Stopping worker in supervisor\nStarting worker in foreground\n{Color.RED}Error running worker in foreground: Spawn failed{Color.RESET}\nRestarting worker in background\n"
        == captured.out
    )

    mock_start_process.assert_called_once_with("worker")
    mock_stop_process.assert_called_once_with("worker")


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_stop_process_exception(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    mock_stop_process.side_effect = SupervisorProcessError("Stop process failed")

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    mock_pty_spawn.assert_not_called()
    mock_start_process.assert_called_once_with("worker")
    mock_stop_process.assert_called_once_with("worker")

    captured = capsys.readouterr()
    assert (
        f"Stopping worker in supervisor\n{Color.RED}Error stopping worker in supervisor: Stop process failed{Color.RESET}\nRestarting worker in background\n"
        == captured.out
    )


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_start_process_exception(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    mock_start_process.side_effect = SupervisorProcessError("Start process failed")

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        foreground(args)

    mock_pty_spawn.assert_called_once_with(["python", "worker.py"])
    mock_start_process.assert_called_once_with("worker")
    mock_stop_process.assert_called_once_with("worker")

    captured = capsys.readouterr()
    assert (
        f"Stopping worker in supervisor\nStarting worker in foreground\nRestarting worker in background\n{Color.RED}Error restarting worker in background: Start process failed{Color.RESET}\n"
        == captured.out
    )


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_with_starting_services(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"]},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTING_SERVICES
        )
        foreground(args)

    # Verify calls
    mock_pty_spawn.assert_called_once_with(["python", "worker.py"])

    mock_start_process.assert_called_once_with("worker")
    mock_stop_process.assert_called_once_with("worker")

    captured = capsys.readouterr()
    assert (
        "Stopping worker in supervisor\nStarting worker in foreground\nRestarting worker in background\n"
        == captured.out
    )


@mock.patch("devservices.commands.foreground.pty.spawn")
@mock.patch("devservices.utils.supervisor.SupervisorManager.start_process")
@mock.patch("devservices.utils.supervisor.SupervisorManager.stop_process")
def test_foreground_multiple_modes_and_dependencies(
    mock_stop_process: mock.Mock,
    mock_start_process: mock.Mock,
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "postgres": {"description": "Postgres"},
                "worker": {"description": "Worker"},
                "consumer": {"description": "Consumer"},
            },
            "modes": {
                "default": ["redis", "worker"],
                "full": ["redis", "postgres", "worker", "consumer"],
            },
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
            "consumer": {
                "command": "python consumer.py",
            },
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
            "postgres": {"image": "postgres:13"},
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="consumer")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "full", StateTables.STARTED_SERVICES
        )
        foreground(args)

    # Verify calls
    mock_pty_spawn.assert_called_once_with(["python", "consumer.py"])

    mock_start_process.assert_called_once_with("consumer")
    mock_stop_process.assert_called_once_with("consumer")

    captured = capsys.readouterr()
    assert (
        "Stopping consumer in supervisor\nStarting consumer in foreground\nRestarting consumer in background\n"
        == captured.out
    )


@mock.patch("devservices.commands.foreground.pty.spawn")
def test_foreground_no_active_modes(
    mock_pty_spawn: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "worker": {"description": "Worker"},
            },
            "modes": {"default": ["worker"], "other": []},
        },
        "x-programs": {
            "worker": {
                "command": "python worker.py",
            },
        },
    }

    service_path = tmp_path / "example-service"
    create_config_file(service_path, config)
    os.chdir(service_path)

    args = Namespace(program_name="worker")

    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "other", StateTables.STARTED_SERVICES
        )
        foreground(args)

    # Should not call pty.spawn since no supervisor programs are active
    mock_pty_spawn.assert_not_called()

    captured = capsys.readouterr()
    assert (
        captured.out
        == f"{Color.RED}Program worker is not running in any active modes of example-service{Color.RESET}\n"
    )
