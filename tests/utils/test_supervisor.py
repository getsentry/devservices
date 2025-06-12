from __future__ import annotations

import socket
import subprocess
import xmlrpc.client
from pathlib import Path
from unittest import mock

import pytest
from freezegun import freeze_time

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorConnectionError
from devservices.exceptions import SupervisorError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.supervisor import SupervisorDaemonState
from devservices.utils.supervisor import SupervisorManager
from devservices.utils.supervisor import SupervisorProcessState
from devservices.utils.supervisor import UnixSocketHTTPConnection
from devservices.utils.supervisor import UnixSocketTransport
from testing.utils import create_config_file


@mock.patch("socket.socket")
def test_unix_socket_http_connection_connect(
    mock_socket: mock.MagicMock, tmp_path: Path
) -> None:
    socket_path = str(tmp_path / "test.sock")
    mock_sock = mock_socket.return_value

    conn = UnixSocketHTTPConnection(socket_path)
    conn.connect()

    mock_socket.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
    mock_sock.connect.assert_called_once_with(socket_path)
    assert conn.sock == mock_sock


@mock.patch("socket.socket")
def test_unix_socket_transport_make_connection(
    mock_socket: mock.MagicMock, tmp_path: Path
) -> None:
    """
    Test that the Unix socket transport correctly attempts to connect to the socket.
    """
    socket_path = str(tmp_path / "test.sock")
    mock_sock = mock_socket.return_value

    transport = UnixSocketTransport(socket_path)

    connection = transport.make_connection("localhost")

    # Connect the socket - this happens when we make an RPC call
    connection.connect()

    # Verify socket creation with correct family and type
    mock_socket.assert_called_with(socket.AF_UNIX, socket.SOCK_STREAM)
    # Verify connection to the right path
    mock_sock.connect.assert_called_with(socket_path)


@pytest.fixture
def supervisor_manager(tmp_path: Path) -> SupervisorManager:
    with mock.patch(
        "devservices.utils.supervisor.DEVSERVICES_SUPERVISOR_CONFIG_DIR", tmp_path
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "test-program": {"description": "Test program"},
                },
                "modes": {},
            },
            "x-programs": {"test_program": {"command": "python test_program.py"}},
        }
        create_config_file(tmp_path, config)
        service_config_path = tmp_path / DEVSERVICES_DIR_NAME / "config.yml"
        return SupervisorManager(
            service_name="test-service", service_config_path=str(service_config_path)
        )


def test_init_with_config_file(supervisor_manager: SupervisorManager) -> None:
    assert supervisor_manager.service_name == "test-service"
    assert "test-service.processes.conf" in supervisor_manager.config_file_path


def test_init_with_nonexistent_config() -> None:
    with pytest.raises(SupervisorConfigError):
        SupervisorManager(
            service_name="test-service", service_config_path="/nonexistent/path.yml"
        )


def test_init_with_empty_config_file(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.supervisor.DEVSERVICES_SUPERVISOR_CONFIG_DIR", tmp_path
    ):
        # Create an empty service config YAML file
        service_config_path = tmp_path / DEVSERVICES_DIR_NAME / "config.yml"
        service_config_path.parent.mkdir(parents=True, exist_ok=True)
        service_config_path.write_text("")

        with pytest.raises(
            SupervisorConfigError, match=f"Config file {service_config_path} is empty"
        ):
            SupervisorManager(
                service_name="test-service",
                service_config_path=str(service_config_path),
            )


def test_supervisor_program_defaults(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.supervisor.DEVSERVICES_SUPERVISOR_CONFIG_DIR", tmp_path
    ):
        # Create a service config YAML file with minimal x-programs config
        service_config_path = tmp_path / DEVSERVICES_DIR_NAME / "config.yml"
        service_config_path.parent.mkdir(parents=True, exist_ok=True)
        service_config_path.write_text(
            """
x-programs:
  test_program:
    command: python test_program.py
            """
        )

        manager = SupervisorManager(
            service_name="test-service", service_config_path=str(service_config_path)
        )

        # Read the generated supervisor config to check defaults were applied
        with open(manager.config_file_path, "r") as f:
            config_content = f.read()

        assert "autostart = false" in config_content
        assert "autorestart = true" in config_content


def test_supervisor_program_custom_values_override_defaults(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.supervisor.DEVSERVICES_SUPERVISOR_CONFIG_DIR", tmp_path
    ):
        # Create a service config YAML file with custom autostart/autorestart values
        service_config_path = tmp_path / DEVSERVICES_DIR_NAME / "config.yml"
        service_config_path.parent.mkdir(parents=True, exist_ok=True)
        service_config_path.write_text(
            """
x-programs:
  test_program:
    command: python test_program.py
    autostart: false
    autorestart: true
            """
        )

        manager = SupervisorManager(
            service_name="test-service", service_config_path=str(service_config_path)
        )

        # Read the generated supervisor config to check custom values were used
        with open(manager.config_file_path, "r") as f:
            config_content = f.read()

        assert "autostart = false" in config_content
        assert "autorestart = true" in config_content


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_rpc_client_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value = mock.MagicMock()
    client = supervisor_manager._get_rpc_client()
    assert client is not None
    mock_rpc_client.assert_called_once()
    transport_arg = mock_rpc_client.call_args[1]["transport"]
    assert isinstance(transport_arg, UnixSocketTransport)
    assert transport_arg.socket_path == supervisor_manager.socket_path


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_rpc_client_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.side_effect = xmlrpc.client.Fault(1, "Error")
    with pytest.raises(SupervisorConnectionError):
        supervisor_manager._get_rpc_client()
    mock_rpc_client.assert_called_once()
    transport_arg = mock_rpc_client.call_args[1]["transport"]
    assert isinstance(transport_arg, UnixSocketTransport)
    assert transport_arg.socket_path == supervisor_manager.socket_path


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_is_program_running_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    assert supervisor_manager._is_program_running("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_is_program_running_program_not_running(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.STOPPED
    }
    assert not supervisor_manager._is_program_running("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_is_program_running_typing_error(
    mock_rpc_client: mock.MagicMock,
    supervisor_manager: SupervisorManager,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = 1
    assert not supervisor_manager._is_program_running("test_program")
    mock_rpc_client.return_value.supervisor.getProcessInfo.side_effect = {
        "state": [SupervisorProcessState.STOPPED]
    }
    assert not supervisor_manager._is_program_running("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_is_program_running_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    assert not supervisor_manager._is_program_running("test_program")


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_supervisor_daemon_success(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getState.side_effect = [
        SupervisorConnectionError("Connection refused"),
        {
            "statecode": SupervisorDaemonState.RUNNING,
            "statename": "RUNNING",
        },
    ]
    supervisor_manager.start_supervisor_daemon()
    mock_subprocess_run.assert_called_once_with(
        ["supervisord", "-c", supervisor_manager.config_file_path], check=True
    )


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch(
    "devservices.utils.supervisor.xmlrpc.client.ServerProxy",
    return_value=mock.MagicMock(),
)
def test_start_supervisor_daemon_already_running(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getState.return_value = {
        "statecode": SupervisorDaemonState.RUNNING,
        "statename": "RUNNING",
    }
    supervisor_manager.start_supervisor_daemon()
    assert mock_rpc_client.return_value.supervisor.getState.call_count == 2
    mock_subprocess_run.assert_called_with(
        ["supervisorctl", "-c", supervisor_manager.config_file_path, "update"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mock_subprocess_run.assert_called_once()


@mock.patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_subprocess_failure(
    mock_subprocess_run: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "supervisord")
    with pytest.raises(SupervisorError):
        supervisor_manager.start_supervisor_daemon()


@mock.patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_file_not_found_failure(
    mock_subprocess_run: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_subprocess_run.side_effect = FileNotFoundError("supervisord")
    with pytest.raises(SupervisorError):
        supervisor_manager.start_supervisor_daemon()


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_supervisor_daemon_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.stop_supervisor_daemon()
    supervisor_manager._get_rpc_client().supervisor.shutdown.assert_called_once()


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_supervisor_daemon_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.shutdown.side_effect = xmlrpc.client.Fault(
        1, "Error"
    )
    with pytest.raises(SupervisorError):
        supervisor_manager.stop_supervisor_daemon()


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_process_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.STOPPED
    }
    supervisor_manager.start_process("test_program")
    supervisor_manager._get_rpc_client().supervisor.startProcess.assert_called_once_with(
        "test_program"
    )


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_process_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.STOPPED
    }
    mock_rpc_client.return_value.supervisor.startProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.start_process("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_process_already_running(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    supervisor_manager.start_process("test_program")
    mock_rpc_client.supervisor.startProcess.assert_not_called()


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_process_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    supervisor_manager.stop_process("test_program")
    supervisor_manager._get_rpc_client().supervisor.stopProcess.assert_called_once_with(
        "test_program"
    )


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_process_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_rpc_client.return_value.supervisor.stopProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.stop_process("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_process_not_running(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.STOPPED
    }
    supervisor_manager.stop_process("test_program")
    mock_rpc_client.supervisor.stopProcess.assert_not_called()


def test_extend_config_file(
    supervisor_manager: SupervisorManager, tmp_path: Path
) -> None:
    assert supervisor_manager.config_file_path == str(
        tmp_path / "test-service.processes.conf"
    )
    with open(supervisor_manager.config_file_path, "r") as f:
        assert (
            f.read()
            == f"""[program:test_program]
autostart = false
autorestart = true
command = python test_program.py

[unix_http_server]
file = {tmp_path}/test-service.sock

[supervisord]
pidfile = {tmp_path}/test-service.pid

[supervisorctl]
serverurl = unix://{tmp_path}/test-service.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

"""
        )


def test_get_program_command_success(
    supervisor_manager: SupervisorManager, tmp_path: Path
) -> None:
    assert (
        supervisor_manager.get_program_command("test_program")
        == "python test_program.py"
    )


def test_get_program_command_program_not_found(
    supervisor_manager: SupervisorManager, tmp_path: Path
) -> None:
    with pytest.raises(
        SupervisorConfigError, match="Program nonexistent_program not found in config"
    ):
        supervisor_manager.get_program_command("nonexistent_program")


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_tail_program_logs_success(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    supervisor_manager.tail_program_logs("test_program")
    mock_subprocess_run.assert_called_once_with(
        [
            "supervisorctl",
            "-c",
            supervisor_manager.config_file_path,
            "tail",
            "-f",
            "test_program",
        ],
        check=True,
    )


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_tail_program_logs_not_running(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.STOPPED
    }
    supervisor_manager.tail_program_logs("test_program")
    captured = capsys.readouterr()
    assert "Program test_program is not running" in captured.out
    mock_subprocess_run.assert_not_called()


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_tail_program_logs_failure(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "supervisorctl")
    with pytest.raises(SupervisorError, match="Failed to tail logs for test_program"):
        supervisor_manager.tail_program_logs("test_program")


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_tail_program_logs_keyboard_interrupt(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_subprocess_run.side_effect = KeyboardInterrupt()
    supervisor_manager.tail_program_logs("test_program")
    mock_subprocess_run.assert_called_once_with(
        [
            "supervisorctl",
            "-c",
            supervisor_manager.config_file_path,
            "tail",
            "-f",
            "test_program",
        ],
        check=True,
    )


@mock.patch("xmlrpc.client.ServerProxy", return_value=mock.MagicMock())
@mock.patch("devservices.utils.supervisor.time.sleep")
def test_wait_for_supervisor_ready_success(
    mock_sleep: mock.MagicMock,
    mock_rpc_client: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    # Mock client that returns a running state
    mock_rpc_client.return_value.supervisor.getState.return_value = {
        "statename": "RUNNING",
        "statecode": SupervisorDaemonState.RUNNING,
    }
    mock_rpc_client.return_value = supervisor_manager._get_rpc_client()
    # Should not raise an exception
    supervisor_manager._wait_for_supervisor_ready()

    # Should not have needed to sleep
    mock_sleep.assert_not_called()


@mock.patch("xmlrpc.client.ServerProxy", return_value=mock.MagicMock())
@mock.patch("devservices.utils.supervisor.time.sleep")
def test_wait_for_supervisor_ready_retries(
    mock_sleep: mock.MagicMock,
    mock_rpc_client: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    # First attempt fails with connection error, second has wrong state, third succeeds
    call1 = SupervisorConnectionError("Connection refused")
    call2 = {"statename": "RUNNING", "statecode": SupervisorDaemonState.RESTARTING}
    call3 = {"statename": "RUNNING", "statecode": SupervisorDaemonState.RUNNING}

    mock_rpc_client.return_value.supervisor.getState.side_effect = [
        call1,
        call2,
        call3,
    ]

    with freeze_time() as frozen_time:
        mock_sleep.side_effect = lambda x: frozen_time.tick(x)
        supervisor_manager._wait_for_supervisor_ready()

    assert mock_sleep.call_count == 2

    assert mock_rpc_client.return_value.supervisor.getState.call_count == 3


@mock.patch("xmlrpc.client.ServerProxy")
@mock.patch("devservices.utils.supervisor.time.sleep")
def test_wait_for_supervisor_ready_timeout(
    mock_sleep: mock.MagicMock,
    mock_rpc_client: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    mock_rpc_client.return_value.supervisor.getState.side_effect = (
        SupervisorConnectionError("Connection refused")
    )

    with (
        freeze_time() as frozen_time,
        pytest.raises(
            SupervisorError, match="Supervisor didn't become ready within 5 seconds"
        ),
    ):
        mock_sleep.side_effect = lambda x: frozen_time.tick(x)
        supervisor_manager._wait_for_supervisor_ready(5, 1)

    assert mock_sleep.call_count == 5

    assert mock_rpc_client.return_value.supervisor.getState.call_count == 5


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_all_process_info_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    """Test successful retrieval of all programs status."""
    mock_process_info = [
        {
            "name": "program1",
            "state": SupervisorProcessState.RUNNING,
            "description": "Running program",
            "pid": 1234,
            "group": "default",
            "start": 1000,
            "now": 1100,
            "stop": 0,
        },
        {
            "name": "program2",
            "state": SupervisorProcessState.STOPPED,
            "description": "Stopped program",
            "pid": 0,
            "group": "workers",
            "start": 0,
            "now": 1100,
            "stop": 1050,
        },
    ]
    mock_rpc_client.return_value.supervisor.getAllProcessInfo.return_value = (
        mock_process_info
    )

    result = supervisor_manager.get_all_process_info()

    assert len(result) == 2

    expected_results = {
        "program1": {
            "name": "program1",
            "state": SupervisorProcessState.RUNNING,
            "state_name": "RUNNING",
            "description": "Running program",
            "pid": 1234,
            "group": "default",
            "uptime": 100,  # 1100 - 1000
            "start_time": 1000,
            "stop_time": 0,
        },
        "program2": {
            "name": "program2",
            "state": SupervisorProcessState.STOPPED,
            "state_name": "STOPPED",
            "description": "Stopped program",
            "pid": 0,
            "group": "workers",
            "uptime": 0,  # No uptime for stopped process
            "start_time": 0,
            "stop_time": 1050,
        },
    }

    for expected, actual in zip(expected_results, result):
        assert actual == expected


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_all_process_info_no_programs(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.has_programs = False

    result = supervisor_manager.get_all_process_info()

    assert result == {}


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_all_process_info_empty_list(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    """Test handling of empty programs list."""
    mock_rpc_client.return_value.supervisor.getAllProcessInfo.return_value = []

    result = supervisor_manager.get_all_process_info()

    assert result == {}


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_all_process_info_xmlrpc_fault(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.getAllProcessInfo.side_effect = (
        xmlrpc.client.Fault(1, "Test error")
    )

    with pytest.raises(
        SupervisorError, match="Failed to get programs status: Test error"
    ):
        supervisor_manager.get_all_process_info()


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_all_process_info_connection_error(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.side_effect = SupervisorConnectionError("Connection failed")

    result = supervisor_manager.get_all_process_info()

    # Should return empty dict when supervisor is not running
    assert result == {}


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_program_logs_success(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    """Test successful retrieval of program logs."""
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_subprocess_run.return_value = subprocess.CompletedProcess(
        args=["supervisorctl", "tail", "test_program"],
        returncode=0,
        stdout="Program logs output",
        stderr="",
    )

    result = supervisor_manager.get_program_logs("test_program")

    assert result == "Program logs output"
    mock_subprocess_run.assert_called_once_with(
        [
            "supervisorctl",
            "-c",
            supervisor_manager.config_file_path,
            "tail",
            "test_program",
        ],
        capture_output=True,
        text=True,
        check=True,
    )


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_program_logs_failure(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    """Test get_program_logs when subprocess fails."""
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(
        1, "supervisorctl", stderr="Command failed"
    )

    with pytest.raises(SupervisorError, match="Failed to get logs for test_program"):
        supervisor_manager.get_program_logs("test_program")


@mock.patch("devservices.utils.supervisor.subprocess.run")
@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_program_logs_with_output_and_error(
    mock_rpc_client: mock.MagicMock,
    mock_subprocess_run: mock.MagicMock,
    supervisor_manager: SupervisorManager,
) -> None:
    """Test get_program_logs returns stdout even when there's stderr."""
    mock_rpc_client.return_value.supervisor.getProcessInfo.return_value = {
        "state": SupervisorProcessState.RUNNING
    }
    mock_subprocess_run.return_value = subprocess.CompletedProcess(
        args=["supervisorctl", "tail", "test_program"],
        returncode=0,
        stdout="Program logs with warnings",
        stderr="Some warnings",
    )

    result = supervisor_manager.get_program_logs("test_program")

    assert result == "Program logs with warnings"
    mock_subprocess_run.assert_called_once_with(
        [
            "supervisorctl",
            "-c",
            supervisor_manager.config_file_path,
            "tail",
            "test_program",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
