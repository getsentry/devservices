from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.list_dependencies import list_dependencies
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import ServiceConfig
from devservices.exceptions import ConfigValidationError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.services import Service


def test_list_dependencies_no_config_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False)

    with pytest.raises(SystemExit):
        list_dependencies(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices list-dependencies sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )


@mock.patch("devservices.commands.list_dependencies.find_matching_service")
def test_list_dependencies_service_not_found(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="nonexistent-service")
    mock_find_matching_service.side_effect = ServiceNotFoundError(
        "Service nonexistent-service not found"
    )

    with pytest.raises(SystemExit) as exc_info:
        list_dependencies(args)

    assert exc_info.value.code == 1

    mock_find_matching_service.assert_called_once_with("nonexistent-service")
    captured = capsys.readouterr()
    assert "Service nonexistent-service not found" in captured.out


@mock.patch("devservices.commands.list_dependencies.find_matching_service")
def test_list_dependencies_config_error(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="test-service")
    mock_find_matching_service.side_effect = ConfigValidationError(
        "Version is required in service config"
    )

    with pytest.raises(SystemExit) as exc_info:
        list_dependencies(args)

    assert exc_info.value.code == 1

    mock_find_matching_service.assert_called_once_with("test-service")
    captured = capsys.readouterr()
    assert "Version is required in service config" in captured.out


@mock.patch("devservices.commands.list_dependencies.find_matching_service")
def test_list_dependencies_no_dependencies(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = Namespace(service_name="test-service")
    service = Service(
        name="test-service",
        repo_path=str(tmp_path),
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={},
            modes={"default": []},
        ),
    )
    mock_find_matching_service.return_value = service

    list_dependencies(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    captured = capsys.readouterr()
    assert "No dependencies found for test-service" in captured.out


@mock.patch("devservices.commands.list_dependencies.find_matching_service")
def test_list_dependencies_with_dependencies(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = Namespace(service_name="test-service")
    service = Service(
        name="test-service",
        repo_path=str(tmp_path),
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={
                "redis": Dependency(description="Redis"),
                "postgres": Dependency(description="Postgres"),
            },
            modes={"default": ["redis", "postgres"]},
        ),
    )
    mock_find_matching_service.return_value = service

    list_dependencies(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    captured = capsys.readouterr()
    assert "Dependencies of test-service:" in captured.out
    assert "- redis: Redis" in captured.out
    assert "- postgres: Postgres" in captured.out
