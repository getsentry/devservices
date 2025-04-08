from __future__ import annotations

import subprocess
import xmlrpc.client
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorConnectionError
from devservices.exceptions import SupervisorError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.supervisor import SupervisorManager


@pytest.fixture
def supervisor_manager(tmp_path: Path) -> SupervisorManager:
    config_file = tmp_path / DEVSERVICES_DIR_NAME / "processes.conf"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        """
[program:test_program]
command = python test_program.py
"""
    )
    return SupervisorManager(port=6001, config_file=str(config_file))


def test_init_with_config_file(supervisor_manager: SupervisorManager) -> None:
    assert supervisor_manager.port == 6001
    assert "devservices/processes.conf" in supervisor_manager.config_file


def test_init_with_invalid_port() -> None:
    with pytest.raises(SupervisorConfigError):
        SupervisorManager(port=None)


def test_init_with_nonexistent_config() -> None:
    with pytest.raises(SupervisorConfigError):
        SupervisorManager(port=6001, config_file="/nonexistent/path.conf")


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_rpc_client_success(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value = MagicMock()
    client = supervisor_manager._get_rpc_client()
    assert client is not None
    mock_rpc_client.assert_called_once_with("http://localhost:6001/RPC2")


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_get_rpc_client_failure(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.side_effect = xmlrpc.client.Fault(1, "Error")
    with pytest.raises(SupervisorConnectionError):
        supervisor_manager._get_rpc_client()
    mock_rpc_client.assert_called_once_with("http://localhost:6001/RPC2")


@patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_success(
    mock_subprocess_run: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.start_supervisor_daemon()
    mock_subprocess_run.assert_called_once_with(
        ["supervisord", "-c", supervisor_manager.config_file], check=True
    )


@patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_subprocess_failure(
    mock_subprocess_run: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "supervisord")
    with pytest.raises(SupervisorError):
        supervisor_manager.start_supervisor_daemon()


@patch("devservices.utils.supervisor.subprocess.run")
def test_start_supervisor_daemon_file_not_found_failure(
    mock_subprocess_run: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_subprocess_run.side_effect = FileNotFoundError("supervisord")
    with pytest.raises(SupervisorError):
        supervisor_manager.start_supervisor_daemon()


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_supervisor_daemon_success(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.stop_supervisor_daemon()
    supervisor_manager._get_rpc_client().supervisor.shutdown.assert_called_once()


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_supervisor_daemon_failure(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.shutdown.side_effect = xmlrpc.client.Fault(
        1, "Error"
    )
    with pytest.raises(SupervisorError):
        supervisor_manager.stop_supervisor_daemon()


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_program_success(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.start_program("test_program")
    supervisor_manager._get_rpc_client().supervisor.startProcess.assert_called_once_with(
        "test_program"
    )


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_start_program_failure(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.startProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.start_program("test_program")


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_program_success(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    supervisor_manager.stop_program("test_program")
    supervisor_manager._get_rpc_client().supervisor.stopProcess.assert_called_once_with(
        "test_program"
    )


@patch("devservices.utils.supervisor.xmlrpc.client.ServerProxy")
def test_stop_program_failure(
    mock_rpc_client: MagicMock, supervisor_manager: SupervisorManager
) -> None:
    mock_rpc_client.return_value.supervisor.stopProcess.side_effect = (
        xmlrpc.client.Fault(1, "Error")
    )
    with pytest.raises(SupervisorProcessError):
        supervisor_manager.stop_program("test_program")
