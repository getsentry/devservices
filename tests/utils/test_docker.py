from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.docker import check_all_containers_healthy
from devservices.utils.docker import check_docker_daemon_running
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import stop_matching_containers
from devservices.utils.docker import wait_for_healthy


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
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}",
            "--filter",
            f"label={DEVSERVICES_ORCHESTRATOR_LABEL}",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
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
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}",
            "--filter",
            f"label={DEVSERVICES_ORCHESTRATOR_LABEL}",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_should_not_remove(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_get_matching_containers.return_value = ["container1", "container2"]
    stop_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL, should_remove=False)
    mock_run.assert_called_once_with(
        ["docker", "stop", "container1", "container2"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_none(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_get_matching_containers.return_value = []
    stop_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL, should_remove=True)
    mock_run.assert_not_called()


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_should_remove(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_get_matching_containers.return_value = ["container1", "container2"]
    stop_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL, should_remove=True)
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


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_stop_error(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    mock_get_matching_containers.return_value = ["container1", "container2"]
    with pytest.raises(DockerError):
        stop_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL, should_remove=True)
    mock_run.assert_called_once_with(
        ["docker", "stop", "container1", "container2"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.run")
@mock.patch("devservices.utils.docker.get_matching_containers")
def test_stop_matching_containers_remove_error(
    mock_get_matching_containers: mock.Mock,
    mock_run: mock.Mock,
) -> None:
    mock_run.side_effect = [None, subprocess.CalledProcessError(1, "cmd")]
    mock_get_matching_containers.return_value = ["container1", "container2"]
    with pytest.raises(DockerError):
        stop_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL, should_remove=True)
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


@mock.patch("devservices.utils.docker.subprocess.check_output", return_value="healthy")
def test_wait_for_healthy_success(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    wait_for_healthy("container1", mock_status)
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    mock_status.failure.assert_not_called()


@mock.patch("devservices.utils.docker.subprocess.check_output", return_value="unknown")
def test_wait_for_healthy_no_healthcheck(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    wait_for_healthy("container1", mock_status)
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    mock_status.failure.assert_not_called()


@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_wait_for_healthy_initial_check_failed_then_success(
    mock_check_output: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = ["unhealthy", "healthy"]
    with mock.patch("devservices.utils.docker.HEALTHCHECK_TIMEOUT", 2), mock.patch(
        "devservices.utils.docker.HEALTHCHECK_INTERVAL", 1
    ):
        wait_for_healthy("container1", mock_status)
    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )
    mock_status.failure.assert_not_called()


@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_wait_for_healthy_docker_error(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerError):
        with mock.patch("devservices.utils.docker.HEALTHCHECK_TIMEOUT", 2), mock.patch(
            "devservices.utils.docker.HEALTHCHECK_INTERVAL", 1
        ):
            wait_for_healthy("container1", mock_status)
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )


@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_wait_for_healthy_healthcheck_failed(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = ["unhealthy", "unhealthy"]
    with mock.patch("devservices.utils.docker.HEALTHCHECK_TIMEOUT", 2), mock.patch(
        "devservices.utils.docker.HEALTHCHECK_INTERVAL", 1
    ):
        wait_for_healthy("container1", mock_status)
    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )
    mock_status.failure.assert_called_once_with(
        "Container container1 did not become healthy within 2 seconds."
    )


@mock.patch("devservices.utils.docker.subprocess.check_output")
@mock.patch(
    "devservices.utils.docker.get_matching_containers",
    return_value=["container1", "container2"],
)
def test_check_all_containers_healthy_success(
    mock_get_matching_containers: mock.Mock, mock_check_output: mock.Mock
) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = ["healthy", "healthy"]
    check_all_containers_healthy(mock_status)
    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container2",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )
    mock_status.failure.assert_not_called()


@mock.patch("devservices.utils.docker.subprocess.check_output")
@mock.patch(
    "devservices.utils.docker.get_matching_containers",
    return_value=["container1", "container2"],
)
def test_check_all_containers_healthy_failure(
    mock_get_matching_containers: mock.Mock, mock_check_output: mock.Mock
) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = ["healthy", "unhealthy", "unhealthy"]
    with mock.patch("devservices.utils.docker.HEALTHCHECK_TIMEOUT", 2), mock.patch(
        "devservices.utils.docker.HEALTHCHECK_INTERVAL", 1
    ):
        check_all_containers_healthy(mock_status)
    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container2",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "container2",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )
    mock_status.failure.assert_called_once_with(
        "Container container2 did not become healthy within 2 seconds."
    )
