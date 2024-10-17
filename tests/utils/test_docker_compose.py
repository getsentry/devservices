from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

from devservices.exceptions import DockerComposeInstallationError
from devservices.utils.docker_compose import check_docker_compose_version
from devservices.utils.docker_compose import install_docker_compose


@mock.patch("subprocess.run")
def test_check_docker_compose_version_success(mock_run: mock.Mock) -> None:
    mock_run.return_value.stdout = "2.29.7\n"
    check_docker_compose_version()  # Should not raise any exception


@mock.patch("subprocess.run")
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_version_unsupported(
    mock_install_docker_compose: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "2.20.0-desktop.1\n"
    check_docker_compose_version()
    assert mock_install_docker_compose.is_called()


@mock.patch("subprocess.run")
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_invalid_version(
    mock_install_docker_compose: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "Unable to find version\n"
    check_docker_compose_version()
    assert mock_install_docker_compose.is_called()


@mock.patch(
    "subprocess.run",
    side_effect=subprocess.CalledProcessError(
        returncode=1, cmd="docker compose version --short"
    ),
)
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_command_failure(
    mock_install_docker_compose: mock.Mock, mock_run: mock.Mock
) -> None:
    check_docker_compose_version()
    assert mock_install_docker_compose.is_called()


@mock.patch("platform.system", return_value="UnsupportedSystem")
@mock.patch("platform.machine", return_value="arm64")
def test_install_docker_compose_unsupported_os(
    mock_system: mock.Mock, mock_machine: mock.Mock
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Unsupported operating system: UnsupportedSystem",
    ):
        install_docker_compose()


@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="unsupported_architecture")
def test_install_docker_compose_unsupported_architecture(
    mock_machine: mock.Mock, mock_system: mock.Mock
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Unsupported architecture: unsupported_architecture",
    ):
        install_docker_compose()


@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    side_effect=Exception("Docker Compose failed"),
)
def test_install_docker_compose_compose_verification_error(
    mock_subprocess_run: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    mock_machine: mock.Mock,
    mock_system: mock.Mock,
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Failed to verify Docker Compose installation: Docker Compose failed",
    ):
        install_docker_compose()


@mock.patch("tempfile.TemporaryDirectory")
@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "version", "--short"],
        returncode=0,
        stdout="2.29.7\n",
    ),
)
def test_install_docker_compose_macos_arm64(
    mock_subprocess_run: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    mock_machine: mock.Mock,
    mock_system: mock.Mock,
    mock_tempdir: mock.Mock,
) -> None:
    mock_tempdir.return_value.__enter__.return_value = "tempdir"
    install_docker_compose()
    mock_urlretrieve.assert_called_once_with(
        "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-darwin-aarch64",
        "tempdir/docker-compose",
    )
    mock_chmod.assert_called_once_with("tempdir/docker-compose", 0o755)
    mock_shutil_move.assert_called_once_with(
        "tempdir/docker-compose",
        os.path.expanduser("~/.docker/cli-plugins/docker-compose"),
    )
    mock_subprocess_run.assert_called_once_with(
        ["docker", "compose", "version", "--short"], capture_output=True, text=True
    )


@mock.patch("tempfile.TemporaryDirectory")
@mock.patch("platform.system", return_value="Linux")
@mock.patch("platform.machine", return_value="x86_64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "version", "--short"],
        returncode=0,
        stdout="2.29.7\n",
    ),
)
def test_install_docker_compose_linux_x86(
    mock_subprocess_run: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    mock_machine: mock.Mock,
    mock_system: mock.Mock,
    mock_tempdir: mock.Mock,
) -> None:
    mock_tempdir.return_value.__enter__.return_value = "tempdir"
    install_docker_compose()
    mock_urlretrieve.assert_called_once_with(
        "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64",
        "tempdir/docker-compose",
    )
    mock_chmod.assert_called_once_with("tempdir/docker-compose", 0o755)
    mock_shutil_move.assert_called_once_with(
        "tempdir/docker-compose",
        os.path.expanduser("~/.docker/cli-plugins/docker-compose"),
    )
    mock_subprocess_run.assert_called_once_with(
        ["docker", "compose", "version", "--short"], capture_output=True, text=True
    )
