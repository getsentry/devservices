from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

from devservices.commands.purge import purge


def test_purge_no_cache(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
        str(tmp_path / ".devservices-cache"),
    ):
        args = Namespace()
        purge(args)


def test_purge_with_cache(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
        str(tmp_path / ".devservices-cache"),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        assert cache_file.exists()

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
