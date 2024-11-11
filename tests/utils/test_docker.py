from __future__ import annotations

import subprocess
from unittest import mock

from devservices.utils.docker import stop_all_running_containers


@mock.patch("subprocess.check_output")
@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_stop_all_running_containers_none_running(
    mock_check_docker_daemon_running: mock.Mock,
    mock_run: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.return_value = b""
    stop_all_running_containers()
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q"], stderr=subprocess.DEVNULL
    )
    mock_run.assert_not_called()


@mock.patch("subprocess.check_output")
@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_stop_all_running_containers(
    mock_check_docker_daemon_running: mock.Mock,
    mock_run: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.return_value = b"container1\ncontainer2\n"
    stop_all_running_containers()
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q"], stderr=subprocess.DEVNULL
    )
    mock_run.assert_called_once_with(
        ["docker", "stop", "container1", "container2"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
