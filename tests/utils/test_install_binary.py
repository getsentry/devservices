from __future__ import annotations

import io
import pathlib
from unittest import mock

import pytest

from devservices.constants import DOWNLOAD_TIMEOUT
from devservices.exceptions import BinaryInstallError
from devservices.utils.install_binary import download_file
from devservices.utils.install_binary import install_binary


@mock.patch(
    "devservices.utils.install_binary.download_file",
    side_effect=Exception("Connection error"),
)
def test_install_docker_compose_connection_error(
    mock_download_file: mock.Mock, capsys: pytest.CaptureFixture[str]
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


@mock.patch("devservices.utils.install_binary.download_file")
def test_install_docker_compose_chmod_file_not_found_error(
    mock_download_file: mock.Mock,
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


@mock.patch("devservices.utils.install_binary.download_file")
@mock.patch("devservices.utils.install_binary.os.chmod")
def test_install_docker_compose_shutil_file_not_found_error(
    mock_chmod: mock.Mock,
    mock_download_file: mock.Mock,
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


@mock.patch("devservices.utils.install_binary.download_file")
@mock.patch(
    "devservices.utils.install_binary.os.chmod",
    side_effect=PermissionError("Insufficient Permissions"),
)
def test_install_docker_compose_chmod_permission_error(
    mock_chmod: mock.Mock,
    mock_download_file: mock.Mock,
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


@mock.patch("devservices.utils.install_binary.download_file")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch(
    "devservices.utils.install_binary.shutil.move",
    side_effect=PermissionError("Insufficient Permissions"),
)
def test_install_docker_compose_shutil_move_permission_error(
    mock_chmod: mock.Mock,
    mock_download_file: mock.Mock,
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


@mock.patch("devservices.utils.install_binary.urlopen")
def test_download_file_uses_timeout(
    mock_urlopen: mock.Mock, tmp_path: pathlib.Path
) -> None:
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(b"binary")
    path = tmp_path / "binary-name"

    download_file("https://example.com/binary", str(path))

    mock_urlopen.assert_called_once_with(
        "https://example.com/binary", timeout=DOWNLOAD_TIMEOUT
    )
    assert path.read_bytes() == b"binary"


@mock.patch("devservices.utils.retry.time.sleep")
@mock.patch(
    "devservices.utils.install_binary.download_file",
    side_effect=[TimeoutError("timed out"), None],
)
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
def test_install_binary_retries_stalled_download(
    mock_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_download_file: mock.Mock,
    mock_sleep: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_binary(
        "binary-name",
        "exec_path",
        "1.0.0",
        "https://example.com/binary",
    )

    assert mock_download_file.call_count == 2
    mock_sleep.assert_called_once_with(1.0)
    mock_move.assert_called_once()
    assert "Download failed (timed out)" in capsys.readouterr().out
