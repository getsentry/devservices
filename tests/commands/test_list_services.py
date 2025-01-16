from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.list_services import list_services
from devservices.utils.state import StateTables
from testing.utils import create_config_file


@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.utils.state.State.get_active_modes_for_service")
def test_list_running_services_starting(
    mock_get_active_modes_for_service: mock.Mock,
    mock_get_service_entries: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.list_services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        mock_get_service_entries.side_effect = [["example-service"], []]
        mock_get_active_modes_for_service.side_effect = [["default"], []]
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
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
        create_config_file(tmp_path / "code" / "example-service", config)

        args = Namespace(service_name=None, all=False)
        list_services(args)

        mock_get_service_entries.assert_has_calls(
            [
                mock.call(StateTables.STARTING_SERVICES),
                mock.call(StateTables.STARTED_SERVICES),
            ]
        )

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            captured.out
            == f"Running services:\n- example-service\n  modes: ['default']\n  status: starting\n  location: {tmp_path / 'code' / 'example-service'}\n"
        )


@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.utils.state.State.get_active_modes_for_service")
def test_list_running_services_started(
    mock_get_active_modes_for_service: mock.Mock,
    mock_get_service_entries: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.list_services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        mock_get_service_entries.side_effect = [[], ["example-service"]]
        mock_get_active_modes_for_service.side_effect = [[], ["default"]]
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
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
        create_config_file(tmp_path / "code" / "example-service", config)

        args = Namespace(service_name=None, all=False)
        list_services(args)

        mock_get_service_entries.assert_has_calls(
            [
                mock.call(StateTables.STARTING_SERVICES),
                mock.call(StateTables.STARTED_SERVICES),
            ]
        )

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            captured.out
            == f"Running services:\n- example-service\n  modes: ['default']\n  status: started\n  location: {tmp_path / 'code' / 'example-service'}\n"
        )


@mock.patch("devservices.utils.state.State.get_service_entries")
@mock.patch("devservices.utils.state.State.get_active_modes_for_service")
def test_list_all_services(
    mock_get_active_modes_for_service: mock.Mock,
    mock_get_service_entries: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.list_services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        mock_get_service_entries.side_effect = [[], ["example-service"]]
        mock_get_active_modes_for_service.side_effect = [[], ["default"]]
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
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
        create_config_file(tmp_path / "code" / "example-service", config)

        args = Namespace(service_name=None, all=True)
        list_services(args)

        mock_get_service_entries.assert_has_calls(
            [
                mock.call(StateTables.STARTING_SERVICES),
                mock.call(StateTables.STARTED_SERVICES),
            ]
        )

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            captured.out
            == f"Services installed locally:\n- example-service\n  modes: ['default']\n  status: started\n  location: {tmp_path / 'code' / 'example-service'}\n"
        )
