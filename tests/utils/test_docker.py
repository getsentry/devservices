from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.docker import check_docker_daemon_running
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import stop_matching_containers


@mock.patch("subprocess.run")
def test_check_docker_daemon_running_error(mock_run: mock.Mock) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerDaemonNotRunningError):
        check_docker_daemon_running()
    mock_run.assert_called_once_with(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=True,
    )


@mock.patch("subprocess.run")
def test_check_docker_daemon_running(mock_run: mock.Mock) -> None:
    check_docker_daemon_running()
    mock_run.assert_called_once_with(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=True,
    )


@mock.patch("subprocess.check_output")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_get_matching_containers(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.return_value = b""
    get_matching_containers("orchestrator=devservices")
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q", "--filter", "label=orchestrator=devservices"],
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.check_output")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_get_matching_containers_docker_daemon_not_running(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.side_effect = DockerDaemonNotRunningError()
    with pytest.raises(DockerDaemonNotRunningError):
        get_matching_containers("orchestrator=devservices")
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_not_called()


@mock.patch("subprocess.check_output")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_get_matching_containers_error(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerError):
        get_matching_containers("orchestrator=devservices")
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q", "--filter", "label=orchestrator=devservices"],
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_should_not_remove(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_get_matching_containers.return_value = ["container1", "container2"]
    stop_matching_containers("orchestrator=devservices", should_remove=False)
    mock_run.assert_called_once_with(
        ["docker", "stop", "container1", "container2"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_should_remove(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_get_matching_containers.return_value = ["container1", "container2"]
    stop_matching_containers("orchestrator=devservices", should_remove=True)
    mock_run.assert_has_calls(
        [
            mock.call(
                ["docker", "stop", "container1", "container2"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            mock.call(
                ["docker", "rm", "container1", "container2"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )
