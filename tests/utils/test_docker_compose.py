from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.exceptions import DockerComposeError
from devservices.utils.docker_compose import check_docker_compose_version


@mock.patch("subprocess.run")
def test_check_docker_compose_version_success(mock_run: mock.Mock) -> None:
    mock_run.return_value.stdout = "2.21.0-desktop.1\n"
    check_docker_compose_version()  # Should not raise any exception


@mock.patch("subprocess.run")
@mock.patch("builtins.print")
def test_check_docker_compose_version_unsupported(
    mock_print: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "2.20.0-desktop.1\n"
    with pytest.raises(SystemExit):
        check_docker_compose_version()
        mock_print.assert_called_with(
            "Docker compose version unsupported, please upgrade to >= 2.21.0"
        )


@mock.patch("subprocess.run")
@mock.patch("builtins.print")
def test_check_docker_compose_version_undetected(
    mock_print: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "invalid_version\n"
    with pytest.raises(SystemExit):
        check_docker_compose_version()
        mock_print.assert_called_with("Unable to detect docker compose version")


@mock.patch("subprocess.run")
def test_check_docker_compose_version_error(mock_run: mock.Mock) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "docker compose version --short", stderr="Error"
    )
    with pytest.raises(DockerComposeError):
        check_docker_compose_version()
