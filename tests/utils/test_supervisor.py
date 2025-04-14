from __future__ import annotations

import subprocess
import xmlrpc.client
from pathlib import Path
from unittest import mock

import pytest

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorConnectionError
from devservices.exceptions import SupervisorError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.supervisor import SupervisorManager
from devservices.utils.supervisor import UnixSocketTransport


@pytest.fixture
def supervisor_manager(tmp_path: Path) -> SupervisorManager:
    with mock.patch(
        "devservices.utils.supervisor.DEVSERVICES_SUPERVISOR_CONFIG_DIR", tmp_path
    ):
        config_file_path = tmp_path / DEVSERVICES_DIR_NAME / "processes.conf"
        config_file_path.parent.mkdir(parents=True, exist_ok=True)
        config_file_path.write_text(
            """
    [program:test_program]
    command = python test_program.py
    """
        )
        return SupervisorManager(
            config_file_path=str(config_file_path), service_name="test-service"
        )


def test_init_with_config_file(supervisor_manager: SupervisorManager) -> None:
    assert supervisor_manager.service_name == "test-service"
    assert "test-service.processes.conf" in supervisor_manager.config_file_path


def test_init_with_nonexistent_config() -> None:
    with pytest.raises(SupervisorConfigError):
        SupervisorManager(
            config_file_path="/nonexistent/path.conf", service_name="test-service"
        )


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


@mock.patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_success(
    mock_subprocess_run: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.start_supervisor_daemon()
    mock_subprocess_run.assert_called_once_with(
        ["supervisord", "-c", supervisor_manager.config_file_path], check=True
    )


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
def test_start_program_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.start_program("test_program")
    supervisor_manager._get_rpc_client().supervisor.startProcess.assert_called_once_with(
        "test_program"
    )


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_program_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.startProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.start_program("test_program")


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_program_success(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.stop_program("test_program")
    supervisor_manager._get_rpc_client().supervisor.stopProcess.assert_called_once_with(
        "test_program"
    )


@mock.patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_program_failure(
    mock_rpc_client: mock.MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.stopProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.stop_program("test_program")


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
