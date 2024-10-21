from __future__ import annotations

from unittest import mock

import pytest

from devservices.exceptions import BinaryInstallError
from devservices.utils.install_binary import install_binary


@mock.patch(
    "devservices.utils.install_binary.urlretrieve",
    side_effect=Exception("Connection error"),
)
def test_install_docker_compose_connection_error(
    mock_urlretrieve: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(
        BinaryInstallError,
        match="Failed to download binary-name after 3 attempts: Connection error",
    ):
        install_binary(
            "binary-name",
            "exec_path",
            "1.0.0",
            "http:://example.com",
        )
        captured = capsys.readouterr()
        assert (
            "Downloading binary-name 1.0.0 from http:://example.com..." in captured.out
        )
        assert "Download failed. Retrying in 1 seconds... (Attempt 1/2)" in captured.out
        assert "Download failed. Retrying in 1 seconds... (Attempt 2/2)" in captured.out


@mock.patch("devservices.utils.install_binary.urlretrieve")
def test_install_docker_compose_chmod_file_not_found_error(
    mock_urlretrieve: mock.Mock,
) -> None:
    with pytest.raises(
        BinaryInstallError,
        match=r"Failed to set executable permissions: \[Errno 2\] No such file or directory:.*",
    ):
        install_binary(
            "binary-name",
            "exec_path",
            "1.0.0",
            "http:://example.com",
        )


@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
def test_install_docker_compose_shutil_file_not_found_error(
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
) -> None:
    with pytest.raises(
        BinaryInstallError,
        match=r"Failed to move binary-name binary to.*",
    ):
        install_binary(
            "binary-name",
            "exec_path",
            "1.0.0",
            "http:://example.com",
        )


@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch(
    "devservices.utils.install_binary.os.chmod",
    side_effect=PermissionError("Insufficient Permissions"),
)
def test_install_docker_compose_chmod_permission_error(
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
) -> None:
    with pytest.raises(
        BinaryInstallError,
        match=r"Failed to set executable permissions: Insufficient Permissions",
    ):
        install_binary(
            "binary-name",
            "exec_path",
            "1.0.0",
            "http:://example.com",
        )


@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch(
    "devservices.utils.install_binary.shutil.move",
    side_effect=PermissionError("Insufficient Permissions"),
)
def test_install_docker_compose_shutil_move_permission_error(
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    mock_move: mock.Mock,
) -> None:
    with pytest.raises(
        BinaryInstallError,
        match=r"Failed to move binary-name binary to.*",
    ):
        install_binary(
            "binary-name",
            "exec_path",
            "1.0.0",
            "http:://example.com",
        )
