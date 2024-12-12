from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from pathlib import Path
from unittest import mock

from freezegun import freeze_time

from devservices.constants import DEVSERVICES_LATEST_VERSION_CACHE_TTL
from devservices.constants import DEVSERVICES_RELEASES_URL
from devservices.utils.check_for_update import check_for_update


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_not_cached(mock_urlopen: mock.Mock, tmp_path: Path) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.0"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.txt"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.os.path.getmtime",
            return_value=datetime.now().timestamp(),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_version = f.read()
            assert cached_version == "1.0.0"


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_no_cache_not_ok(
    mock_urlopen: mock.Mock, tmp_path: Path
) -> None:
    mock_response = mock.mock_open().return_value
    mock_response.status = 500
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.txt"
    with (
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        assert check_for_update() is None
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        assert not cached_file.exists()


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_cached_fresh(mock_urlopen: mock.Mock, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.txt"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.os.path.getmtime",
            return_value=(
                datetime.now()
                - DEVSERVICES_LATEST_VERSION_CACHE_TTL
                + timedelta(minutes=1)
            ).timestamp(),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        cache_dir.mkdir()
        cached_file.write_text("1.0.0")
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_not_called()


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_cached_stale_without_update(
    mock_urlopen: mock.Mock, tmp_path: Path
) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.0"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.txt"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.os.path.getmtime",
            return_value=(
                datetime.now() - DEVSERVICES_LATEST_VERSION_CACHE_TTL
            ).timestamp(),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        cache_dir.mkdir()
        cached_file.write_text("1.0.0")
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_version = f.read()
            assert cached_version == "1.0.0"


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_cached_stale_with_update(
    mock_urlopen: mock.Mock, tmp_path: Path
) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.1"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.txt"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.os.path.getmtime",
            return_value=(
                datetime.now()
                - DEVSERVICES_LATEST_VERSION_CACHE_TTL
                - timedelta(minutes=1)
            ).timestamp(),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        cache_dir.mkdir()
        cached_file.write_text("1.0.0")
        assert check_for_update() == "1.0.1"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_data = f.read()
            assert cached_data == "1.0.1"
