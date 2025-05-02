from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.reset import reset
from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file


@mock.patch(
    "devservices.commands.reset.get_matching_containers",
    side_effect=DockerDaemonNotRunningError(),
)
def test_reset_docker_daemon_not_running(
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="test-service")

    reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=test-service"]
    )

    captured = capsys.readouterr()
    assert (
        "Unable to connect to the docker daemon. Is the docker daemon running?"
        in captured.out.strip()
    )


@mock.patch(
    "devservices.commands.reset.get_matching_containers",
    side_effect=DockerError(
        command="test-command", returncode=1, stdout="", stderr="test error"
    ),
)
def test_reset_failed_to_get_matching_containers(
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace()
    args.service_name = "test-service"

    with pytest.raises(SystemExit):
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=test-service"]
    )

    captured = capsys.readouterr()
    assert "Failed to get matching containers" in captured.out


@mock.patch("devservices.commands.reset.get_matching_containers", return_value=[])
def test_reset_no_matching_containers(
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace()
    args.service_name = "test-service"

    with pytest.raises(SystemExit):
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=test-service"]
    )

    captured = capsys.readouterr()
    assert "No containers found for test-service" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["test-service"]
)
@mock.patch("devservices.commands.reset.get_volumes_for_containers", return_value=[])
def test_reset_no_matching_volumes(
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="test-service")

    with pytest.raises(SystemExit):
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=test-service"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["test-service"])

    captured = capsys.readouterr()
    assert "No volumes found for test-service" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["test-service"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    side_effect=DockerError(
        command="test-command", returncode=1, stdout="", stderr="test error"
    ),
)
def test_reset_failed_to_get_matching_volumes(
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace()
    args.service_name = "test-service"

    with pytest.raises(SystemExit):
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=test-service"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["test-service"])

    captured = capsys.readouterr()
    assert "Failed to get matching volumes" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["redis"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    return_value=["redis-volume"],
)
@mock.patch("devservices.commands.reset.down")
@mock.patch(
    "devservices.commands.reset.stop_containers",
    side_effect=DockerError(
        command="test-command", returncode=1, stdout="", stderr="test error"
    ),
)
@mock.patch("devservices.commands.reset.remove_docker_resources")
def test_reset_with_service_name_container_removal_error(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_down: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="redis")
    service_path = tmp_path / "code" / "test-service"
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
    create_config_file(service_path, config)
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        with pytest.raises(SystemExit):
            reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=redis"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["redis"])
    mock_down.assert_called_once_with(
        Namespace(service_name="test-service", exclude_local=True)
    )
    mock_stop_containers.assert_called_once_with(["redis"], should_remove=True)
    mock_remove_docker_resources.assert_not_called()

    captured = capsys.readouterr()
    assert "Resetting docker volumes for redis" in captured.out
    assert "Bringing down test-service in order to safely reset redis" in captured.out
    assert "Failed to stop and remove redis\nError: test error" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["redis"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    return_value=["redis-volume"],
)
@mock.patch("devservices.commands.reset.down")
@mock.patch("devservices.commands.reset.stop_containers")
@mock.patch(
    "devservices.commands.reset.remove_docker_resources",
    side_effect=DockerError(
        command="test-command", returncode=1, stdout="", stderr="test error"
    ),
)
def test_reset_with_service_name_volume_removal_error(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_down: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="redis")
    service_path = tmp_path / "code" / "test-service"
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
    create_config_file(service_path, config)
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        with pytest.raises(SystemExit):
            reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=redis"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["redis"])
    mock_down.assert_called_once_with(
        Namespace(service_name="test-service", exclude_local=True)
    )
    mock_stop_containers.assert_called_once_with(["redis"], should_remove=True)
    mock_remove_docker_resources.assert_called_once_with("volume", ["redis-volume"])

    captured = capsys.readouterr()
    assert "Resetting docker volumes for redis" in captured.out
    assert "Bringing down test-service in order to safely reset redis" in captured.out
    assert "Failed to remove volumes redis-volume\nError: test error" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["redis"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    return_value=["redis-volume"],
)
@mock.patch("devservices.commands.reset.down")
@mock.patch("devservices.commands.reset.stop_containers")
@mock.patch("devservices.commands.reset.remove_docker_resources")
def test_reset_with_service_name(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_down: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="redis")
    service_path = tmp_path / "code" / "test-service"
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
    create_config_file(service_path, config)
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=redis"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["redis"])
    mock_down.assert_called_once_with(
        Namespace(service_name="test-service", exclude_local=True)
    )
    mock_stop_containers.assert_called_once_with(["redis"], should_remove=True)
    mock_remove_docker_resources.assert_called_once_with("volume", ["redis-volume"])

    captured = capsys.readouterr()
    assert "Resetting docker volumes for redis" in captured.out
    assert "Docker volumes have been reset for redis" in captured.out
    assert "Bringing down test-service in order to safely reset redis" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["redis"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    return_value=["redis-volume"],
)
@mock.patch("devservices.commands.reset.down")
@mock.patch("devservices.commands.reset.stop_containers")
@mock.patch("devservices.commands.reset.remove_docker_resources")
def test_reset_with_multiple_services_depending_on_same_service(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_down: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="redis")
    service_1_path = tmp_path / "code" / "test-service-1"
    service_1_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service-1",
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
    service_2_path = tmp_path / "code" / "test-service-2"
    service_2_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service-2",
            "dependencies": {
                "redis": {"description": "Redis"},
            },
            "modes": {"default": ["redis"]},
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }
    create_config_file(service_1_path, service_1_config)
    create_config_file(service_2_path, service_2_config)
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service-1", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "test-service-2", "default", StateTables.STARTED_SERVICES
        )
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=redis"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["redis"])
    mock_down.assert_has_calls(
        [
            mock.call(Namespace(service_name="test-service-1", exclude_local=True)),
            mock.call(Namespace(service_name="test-service-2", exclude_local=True)),
        ],
        any_order=True,
    )
    mock_stop_containers.assert_called_once_with(["redis"], should_remove=True)
    mock_remove_docker_resources.assert_called_once_with("volume", ["redis-volume"])

    captured = capsys.readouterr()
    assert "Resetting docker volumes for redis" in captured.out
    assert "Docker volumes have been reset for redis" in captured.out
    assert "Bringing down test-service-1 in order to safely reset redis" in captured.out
    assert "Bringing down test-service-2 in order to safely reset redis" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["clickhouse"]
)
@mock.patch(
    "devservices.commands.reset.get_volumes_for_containers",
    return_value=["clickhouse-volume"],
)
@mock.patch("devservices.commands.reset.down")
@mock.patch("devservices.commands.reset.stop_containers")
@mock.patch("devservices.commands.reset.remove_docker_resources")
def test_reset_with_multiple_services_depending_on_different_service(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_down: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="clickhouse")
    service_1_path = tmp_path / "code" / "test-service-1"
    service_1_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service-1",
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
    service_2_path = tmp_path / "code" / "test-service-2"
    service_2_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service-2",
            "dependencies": {
                "redis": {"description": "Redis"},
            },
            "modes": {"default": ["redis"]},
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
        },
    }
    create_config_file(service_1_path, service_1_config)
    create_config_file(service_2_path, service_2_config)
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service-1", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "test-service-2", "default", StateTables.STARTED_SERVICES
        )
        reset(args)

    mock_get_matching_containers.assert_called_once_with(
        [DEVSERVICES_ORCHESTRATOR_LABEL, "com.docker.compose.service=clickhouse"]
    )
    mock_get_volumes_for_containers.assert_called_once_with(["clickhouse"])
    mock_down.assert_called_once_with(
        Namespace(service_name="test-service-1", exclude_local=True)
    )
    mock_stop_containers.assert_called_once_with(["clickhouse"], should_remove=True)
    mock_remove_docker_resources.assert_called_once_with(
        "volume", ["clickhouse-volume"]
    )

    captured = capsys.readouterr()
    assert "Resetting docker volumes for clickhouse" in captured.out
    assert "Docker volumes have been reset for clickhouse" in captured.out
    assert (
        "Bringing down test-service-1 in order to safely reset clickhouse"
        in captured.out
    )
