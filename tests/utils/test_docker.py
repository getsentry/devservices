from __future__ import annotations

import subprocess
from datetime import timedelta
from unittest import mock

import pytest
from freezegun import freeze_time

from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.constants import DOCKER_NETWORK_NAME
from devservices.constants import HEALTHCHECK_INTERVAL
from devservices.constants import HEALTHCHECK_TIMEOUT
from devservices.exceptions import ContainerHealthcheckFailedError
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.docker import check_all_containers_healthy
from devservices.utils.docker import check_docker_daemon_running
from devservices.utils.docker import ContainerNames
from devservices.utils.docker import get_matching_containers
from devservices.utils.docker import get_matching_networks
from devservices.utils.docker import get_volumes_for_containers
from devservices.utils.docker import stop_containers
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
    mock_check_output.return_value = "container1\ncontainer2"
    matching_containers = get_matching_containers(DEVSERVICES_ORCHESTRATOR_LABEL)
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label={DEVSERVICES_ORCHESTRATOR_LABEL}",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    assert matching_containers == ["container1", "container2"]


@mock.patch("subprocess.check_output")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_get_matching_networks(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.return_value = "network1\nnetwork2"
    matching_networks = get_matching_networks(DOCKER_NETWORK_NAME)
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"name={DOCKER_NETWORK_NAME}",
            "--format",
            "{{.ID}}",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    assert matching_networks == ["network1", "network2"]


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
def test_get_matching_networks_docker_daemon_not_running(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.side_effect = DockerDaemonNotRunningError()
    with pytest.raises(DockerDaemonNotRunningError):
        get_matching_networks(DOCKER_NETWORK_NAME)
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
            "-a",
            "-q",
            "--filter",
            f"label={DEVSERVICES_ORCHESTRATOR_LABEL}",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.check_output")
@mock.patch("devservices.utils.docker.check_docker_daemon_running")
def test_get_matching_networks_error(
    mock_check_docker_daemon_running: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_check_docker_daemon_running.return_value = None
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerError):
        get_matching_networks(DOCKER_NETWORK_NAME)
    mock_check_docker_daemon_running.assert_called_once()
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"name={DOCKER_NETWORK_NAME}",
            "--format",
            "{{.ID}}",
        ],
        text=True,
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
    mock_check_output.return_value = "volume1\nvolume2"
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
        text=True,
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
        text=True,
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
                ["docker", "container", "rm", *containers],
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
                ["docker", "container", "rm", *containers],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
    )


@mock.patch("devservices.utils.docker.subprocess.check_output", return_value="healthy")
def test_wait_for_healthy_success(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    wait_for_healthy(
        ContainerNames(name="devservices-container1", short_name="container1"),
        mock_status,
    )
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "devservices-container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    mock_status.failure.assert_not_called()
    mock_status.info.assert_has_calls(
        [
            mock.call("container1 is healthy"),
        ]
    )


@mock.patch("devservices.utils.docker.subprocess.check_output", return_value="unknown")
def test_wait_for_healthy_no_healthcheck(mock_check_output: mock.Mock) -> None:
    mock_status = mock.Mock()
    wait_for_healthy(
        ContainerNames(name="devservices-container1", short_name="container1"),
        mock_status,
    )
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "devservices-container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    mock_status.failure.assert_not_called()
    mock_status.warning.assert_has_calls(
        [
            mock.call("WARNING: Container container1 does not have a healthcheck"),
        ]
    )


@mock.patch("devservices.utils.docker.subprocess.check_output")
@mock.patch("devservices.utils.docker.time.sleep")
def test_wait_for_healthy_initial_check_failed_then_success(
    mock_sleep: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = ["unhealthy", "healthy"]

    with (freeze_time("2024-05-14 00:00:00") as frozen_time,):
        mock_sleep.side_effect = lambda _: frozen_time.tick(timedelta(seconds=1))
        wait_for_healthy(
            ContainerNames(name="devservices-container1", short_name="container1"),
            mock_status,
        )

    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "devservices-container1",
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
                    "devservices-container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )
    mock_sleep.assert_called_once_with(HEALTHCHECK_INTERVAL)
    mock_status.failure.assert_not_called()
    mock_status.info.assert_has_calls(
        [
            mock.call("container1 is healthy"),
        ]
    )


@mock.patch("devservices.utils.docker.subprocess.check_output")
@mock.patch("devservices.utils.docker.time.sleep")
def test_wait_for_healthy_docker_error(
    mock_sleep: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "cmd")
    with pytest.raises(DockerError):
        with freeze_time("2024-05-14 00:00:00") as frozen_time:
            mock_sleep.side_effect = lambda _: frozen_time.tick(timedelta(seconds=1))
            wait_for_healthy(
                ContainerNames(name="devservices-container1", short_name="container1"),
                mock_status,
            )
    mock_check_output.assert_called_once_with(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
            "devservices-container1",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )


@mock.patch("devservices.utils.docker.subprocess.check_output")
@mock.patch("devservices.utils.docker.time.sleep")
def test_wait_for_healthy_healthcheck_failed(
    mock_sleep: mock.Mock,
    mock_check_output: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_check_output.return_value = "unhealthy"
    with freeze_time("2024-05-14 00:00:00") as frozen_time:
        with pytest.raises(ContainerHealthcheckFailedError):
            mock_sleep.side_effect = lambda _: frozen_time.tick(
                timedelta(seconds=HEALTHCHECK_TIMEOUT / 2)
            )
            wait_for_healthy(
                ContainerNames(name="devservices-container1", short_name="container1"),
                mock_status,
            )
    mock_check_output.assert_has_calls(
        [
            mock.call(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                    "devservices-container1",
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
                    "devservices-container1",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
            ),
        ]
    )


@mock.patch("devservices.utils.docker.wait_for_healthy")
def test_check_all_containers_healthy_success(
    mock_wait_for_healthy: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_wait_for_healthy.side_effect = [None, None]
    check_all_containers_healthy(
        mock_status,
        [
            ContainerNames(name="devservices-container1", short_name="container1"),
            ContainerNames(name="devservices-container2", short_name="container2"),
        ],
    )
    mock_status.info.assert_has_calls(
        [
            mock.call("Waiting for all containers to be healthy"),
        ]
    )
    mock_wait_for_healthy.assert_has_calls(
        [
            mock.call(
                ContainerNames(name="devservices-container1", short_name="container1"),
                mock_status,
            ),
            mock.call(
                ContainerNames(name="devservices-container2", short_name="container2"),
                mock_status,
            ),
        ]
    )


@mock.patch("devservices.utils.docker.wait_for_healthy")
def test_check_all_containers_healthy_failure(
    mock_wait_for_healthy: mock.Mock,
) -> None:
    mock_status = mock.Mock()
    mock_wait_for_healthy.side_effect = [
        None,
        ContainerHealthcheckFailedError("container2", HEALTHCHECK_TIMEOUT),
    ]
    with pytest.raises(ContainerHealthcheckFailedError):
        check_all_containers_healthy(
            mock_status,
            [
                ContainerNames(name="devservices-container1", short_name="container1"),
                ContainerNames(name="devservices-container2", short_name="container2"),
            ],
        )
    mock_wait_for_healthy.assert_has_calls(
        [
            mock.call(
                ContainerNames(name="devservices-container1", short_name="container1"),
                mock_status,
            ),
            mock.call(
                ContainerNames(name="devservices-container2", short_name="container2"),
                mock_status,
            ),
        ]
    )
