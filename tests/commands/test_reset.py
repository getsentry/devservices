from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.reset import reset
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file


@mock.patch("devservices.commands.reset.get_matching_containers", return_value=[])
def test_reset_no_matching_containers(
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace()
    args.service_name = "test-service"

    with pytest.raises(SystemExit):
        reset(args)

    captured = capsys.readouterr()
    assert "No containers found for test-service" in captured.out


@mock.patch(
    "devservices.commands.reset.get_matching_containers", return_value=["test-service"]
)
@mock.patch("devservices.commands.reset.get_volumes_for_containers", return_value=[])
def test_reset_no_matching_volumes(
    mock_get_matching_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace()
    args.service_name = "test-service"

    with pytest.raises(SystemExit):
        reset(args)

    captured = capsys.readouterr()
    assert "No volumes found for test-service" in captured.out


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
    args = Namespace()
    args.service_name = "redis"
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
    captured = capsys.readouterr()
    assert "Resetting docker volumes for redis" in captured.out
    assert "Docker volumes have been reset for redis" in captured.out
    mock_down.assert_called_once_with(Namespace(service_name="test-service"))
    mock_stop_containers.assert_called_once_with(["redis"], should_remove=True)
    mock_remove_docker_resources.assert_called_once_with("volume", ["redis-volume"])
