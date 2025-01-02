from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.status import status
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import ServiceConfig
from devservices.exceptions import DependencyError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.services import Service


def test_status_no_config_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False)

    with pytest.raises(SystemExit):
        status(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices status sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )


@mock.patch("devservices.commands.status._status")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_service_not_found(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_status: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = Namespace(service_name="nonexistent-service")
    mock_find_matching_service.side_effect = ServiceNotFoundError("Service not found")

    with pytest.raises(SystemExit) as exc_info:
        status(args)

    assert exc_info.value.code == 1

    mock_find_matching_service.assert_called_once_with("nonexistent-service")
    mock_install_and_verify_dependencies.assert_not_called()
    mock_status.assert_not_called()

    captured = capsys.readouterr()
    assert "Service not found" in captured.out


@mock.patch("devservices.commands.status._status")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_dependency_error(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_status: mock.Mock,
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
    mock_install_and_verify_dependencies.side_effect = DependencyError(
        repo_name="test-service", repo_link=str(tmp_path), branch="main"
    )

    with pytest.raises(SystemExit) as exc_info:
        status(args)

    assert exc_info.value.code == 1

    mock_find_matching_service.assert_called_once_with("test-service")
    mock_install_and_verify_dependencies.assert_called_once_with(service)
    mock_status.assert_not_called()

    captured = capsys.readouterr()
    assert f"DependencyError: test-service ({str(tmp_path)}) on main" in captured.out


@mock.patch("devservices.commands.status._status")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_service_not_running(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_status: mock.Mock,
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
    mock_install_and_verify_dependencies.return_value = set()
    mock_status.return_value = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="")
    ]

    status(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    mock_install_and_verify_dependencies.assert_called_once_with(service)
    mock_status.assert_called_once_with(service, set(), [])

    captured = capsys.readouterr()
    assert "test-service is not running" in captured.out


@mock.patch("devservices.commands.status._status")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_service_running(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_status: mock.Mock,
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
    mock_install_and_verify_dependencies.return_value = set()
    mock_status.return_value = [
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Service": "test-service", "State": "running", "Name": "test-container", "Health": "healthy", "RunningFor": "2 days ago", "Publishers": [{"URL": "http://localhost:8080", "PublishedPort": 8080, "TargetPort": 8080, "Protocol": "tcp"}]}\n',
        )
    ]

    status(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    mock_install_and_verify_dependencies.assert_called_once_with(service)
    mock_status.assert_called_once_with(service, set(), [])

    captured = capsys.readouterr()
    assert (
        """Service: test-service

========================================
test-service
Container: test-container
Status: running
Health: healthy
Uptime: 2 days ago
Ports:
  http://localhost:8080:8080 -> 8080/tcp
----------------------------------------

"""
        == captured.out
    )


@mock.patch("devservices.commands.status._status")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_services_running_sorted_order(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_status: mock.Mock,
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
                "test-dependency": Dependency(
                    description="Test dependency",
                )
            },
            modes={"default": []},
        ),
    )
    mock_find_matching_service.return_value = service
    mock_install_and_verify_dependencies.return_value = set()
    mock_status.return_value = [
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Service": "test-service", "State": "running", "Name": "test-container", "Health": "healthy", "RunningFor": "2 days ago", "Publishers": [{"URL": "http://localhost:8080", "PublishedPort": 8080, "TargetPort": 8080, "Protocol": "tcp"}]}\n',
        ),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Service": "test-dependency", "State": "running", "Name": "test-dependency-container", "Health": "healthy", "RunningFor": "2 days ago", "Publishers": [{"URL": "http://localhost:8081", "PublishedPort": 8081, "TargetPort": 8081, "Protocol": "tcp"}]}\n',
        ),
    ]

    status(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    mock_install_and_verify_dependencies.assert_called_once_with(service)
    mock_status.assert_called_once_with(service, set(), [])

    captured = capsys.readouterr()
    assert (
        """Service: test-service

========================================
test-dependency
Container: test-dependency-container
Status: running
Health: healthy
Uptime: 2 days ago
Ports:
  http://localhost:8081:8081 -> 8081/tcp
----------------------------------------
test-service
Container: test-container
Status: running
Health: healthy
Uptime: 2 days ago
Ports:
  http://localhost:8080:8080 -> 8080/tcp
----------------------------------------

"""
        == captured.out
    )
