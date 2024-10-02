from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from devservices.exceptions import DockerComposeError
from devservices.utils.docker_compose import check_docker_compose_version


def test_check_docker_compose_version_success() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "2.21.0-desktop.1\n"
        check_docker_compose_version()  # Should not raise any exception


def test_check_docker_compose_version_unsupported() -> None:
    with patch("subprocess.run") as mock_run, patch(
        "builtins.print"
    ) as mock_print, patch("sys.exit") as mock_exit:
        mock_run.return_value.stdout = "2.20.0-desktop.1\n"
        check_docker_compose_version()
        mock_print.assert_called_with(
            "Docker compose version unsupported, please upgrade to >= 2.21.0"
        )
        mock_exit.assert_called_with(1)


def test_check_docker_compose_version_undetected() -> None:
    with patch("subprocess.run") as mock_run, patch(
        "builtins.print"
    ) as mock_print, patch("sys.exit") as mock_exit:
        mock_run.return_value.stdout = "invalid_version\n"
        check_docker_compose_version()
        mock_print.assert_called_with("Unable to detect docker compose version")
        mock_exit.assert_called_with(1)


def test_check_docker_compose_version_error() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "docker compose version --short", stderr="Error"
        )
        with pytest.raises(DockerComposeError):
            check_docker_compose_version()
