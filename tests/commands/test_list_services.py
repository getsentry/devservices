from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.list_services import list_services
from devservices.utils.state import State
from testing.utils import create_config_file


def test_list_running_services(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with mock.patch(
        "devservices.commands.list_services.get_coderoot",
        return_value=str(tmp_path / "code"),
    ), mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
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

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            captured.out
            == f"Running services:\n- example-service\n  modes: ['default']\n  status: running\n  location: {tmp_path / 'code' / 'example-service'}\n"
        )


def test_list_all_services(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch(
        "devservices.commands.list_services.get_coderoot",
        return_value=str(tmp_path / "code"),
    ), mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
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

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            captured.out
            == f"Services installed locally:\n- example-service\n  modes: ['default']\n  status: running\n  location: {tmp_path / 'code' / 'example-service'}\n"
        )
