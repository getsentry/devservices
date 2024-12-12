from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from unittest import mock

from freezegun import freeze_time

from devservices.constants import DEVSERVICES_RELEASES_URL
from devservices.utils.check_for_update import check_for_update


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_not_cached(mock_urlopen: mock.Mock, tmp_path: Path) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.0"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    with (
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(tmp_path / "cache"),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(tmp_path / "cache" / "latest_version.json"),
        ),
    ):
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_cached_fresh(mock_urlopen: mock.Mock, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.json"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        fourteen_minutes_ago = datetime.now() - timedelta(minutes=14)
        cache_dir.mkdir()
        cached_file.write_text(
            f"""{{
            "latest_version": "1.0.0",
            "timestamp": "{fourteen_minutes_ago.isoformat()}"
        }}"""
        )
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
    cached_file = cache_dir / "latest_version.json"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        sixteen_minutes_ago = datetime.now() - timedelta(minutes=16)
        cache_dir.mkdir()
        cached_file.write_text(
            f"""{{
            "latest_version": "1.0.0",
            "timestamp": "{sixteen_minutes_ago.isoformat()}"
        }}"""
        )
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_data = json.load(f)
            cached_data["latest_version"] = "1.0.0"
            cached_data["timestamp"] = datetime.now().isoformat()


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_cached_stale_with_update(
    mock_urlopen: mock.Mock, tmp_path: Path
) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.1"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.json"
    with (
        freeze_time("2024-05-14 05:43:21"),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_CACHE_DIR",
            str(cache_dir),
        ),
        mock.patch(
            "devservices.utils.check_for_update.DEVSERVICES_LATEST_VERSION_CACHE_FILE",
            str(cached_file),
        ),
    ):
        sixteen_minutes_ago = datetime.now() - timedelta(minutes=16)
        cache_dir.mkdir()
        cached_file.write_text(
            f"""{{
            "latest_version": "1.0.0",
            "timestamp": "{sixteen_minutes_ago.isoformat()}"
        }}"""
        )
        assert check_for_update() == "1.0.1"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_data = json.load(f)
            cached_data["latest_version"] = "1.0.1"
            cached_data["timestamp"] = datetime.now().isoformat()


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_invalid_cached_value(
    mock_urlopen: mock.Mock, tmp_path: Path
) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.0"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.json"
    with (
        freeze_time("2024-05-14 05:43:21"),
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
        cached_file.write_text("invalid json")
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_data = json.load(f)
            cached_data["latest_version"] = "1.0.0"
            cached_data["timestamp"] = datetime.now().isoformat()


@mock.patch("devservices.utils.check_for_update.urlopen")
def test_check_for_update_invalid_date(mock_urlopen: mock.Mock, tmp_path: Path) -> None:
    mock_response = mock.mock_open(read_data=b'{"tag_name": "1.0.0"}').return_value
    mock_response.status = 200
    mock_urlopen.side_effect = [mock_response]
    cache_dir = tmp_path / "cache"
    cached_file = cache_dir / "latest_version.json"
    with (
        freeze_time("2024-05-14 05:43:21"),
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
        cached_file.write_text(
            """{{
            "latest_version": "1.0.0",
            "timestamp": "invalid"
        }}"""
        )
        assert check_for_update() == "1.0.0"
        mock_urlopen.assert_called_once_with(DEVSERVICES_RELEASES_URL)

        with cached_file.open("r") as f:
            cached_data = json.load(f)
            cached_data["latest_version"] = "1.0.0"
            cached_data["timestamp"] = datetime.now().isoformat()
