from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.docker import check_docker_daemon_running
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import get_volumes_for_containers
from devservices.utils.docker import stop_containers


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
    get_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL)
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q", "--filter", f"label={DEVSERVICES_ORCHESTRATOR_LABEL}"],
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
        get_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL)
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
        get_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL)
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        ["docker", "ps", "-q", "--filter", f"label={DEVSERVICES_ORCHESTRATOR_LABEL}"],
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.check_output")
def test_get_volumes_for_containers_empty(mock_check_output: mock.Mock) -> None:
    assert get_volumes_for_containers([]) == set()
    mock_check_output.assert_not_called()


@mock.patch("subprocess.check_output")
def test_get_volumes_for_containers(
    mock_check_output: mock.Mock,
) -> None:
    mock_check_output.return_value = b"volume1\nvolume2"
    assert get_volumes_for_containers(["container1", "container2"]) == {
        "volume1",
        "volume2",
    }
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "--format",
            "{{ range .Mounts }}{{ .Name }}\n{{ end }}",
            "container1",
            "container2",
        ],
        stderr=mock.ANY,
    )


@mock.patch("subprocess.check_output")
def test_get_volumes_for_containers_error(
    mock_check_output: mock.Mock,
) -> None:
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerError):
        get_volumes_for_containers(["container1", "container2"])
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "--format",
            "{{ range .Mounts }}{{ .Name }}\n{{ end }}",
            "container1",
            "container2",
        ],
        stderr=mock.ANY,
    )


@mock.patch("subprocess.run")
def test_stop_containers_should_not_remove(
    mock_run: mock.Mock,
) -> None:
    containers = ["container1", "container2"]
    stop_containers(containers, should_remove=False)
    mock_run.assert_called_once_with(
        ["docker", "stop", *containers],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
def test_stop_containers_none(
    mock_run: mock.Mock,
) -> None:
    stop_containers([], should_remove=True)
    mock_run.assert_not_called()


@mock.patch("subprocess.run")
def test_stop_containers_should_remove(
    mock_run: mock.Mock,
) -> None:
    containers = ["container1", "container2"]
    stop_containers(containers, should_remove=True)
    mock_run.assert_has_calls(
        [
            mock.call(
                ["docker", "stop", *containers],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            mock.call(
                ["docker", "rm", *containers],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )


@mock.patch("subprocess.run")
def test_stop_containers_stop_error(
    mock_run: mock.Mock,
) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    containers = ["container1", "container2"]
    with pytest.raises(DockerError):
        stop_containers(containers, should_remove=True)
    mock_run.assert_called_once_with(
        ["docker", "stop", *containers],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
def test_stop_containers_remove_error(
    mock_run: mock.Mock,
) -> None:
    mock_run.side_effect = [None, subprocess.CalledProcessError(1, "cmd")]
    containers = ["container1", "container2"]
    with pytest.raises(DockerError):
        stop_containers(containers, should_remove=True)
    mock_run.assert_has_calls(
        [
            mock.call(
                ["docker", "stop", *containers],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            mock.call(
                ["docker", "rm", *containers],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )
