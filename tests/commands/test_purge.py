from __future__ import annotations

import builtins
from argparse import Namespace
from pathlib import Path
from unittest import mock

from devservices.commands.purge import purge
from devservices.utils.state import State


def fake_yes_input(_: str) -> str:
    return "yes"


def fake_no_input(_: str) -> str:
    return "no"


def test_purge_not_confirmed(tmp_path: Path) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", fake_no_input),
    ):
        args = Namespace()
        purge(args)


@mock.patch("devservices.utils.docker.subprocess.run")
@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_purge_with_cache_and_state_and_no_running_containers_confirmed(
    mock_check_output: mock.Mock, mock_run: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", fake_yes_input),
    ):
        # Mock return value for "docker ps -q"
        mock_check_output.return_value = b""
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.add_started_service("test-service", "test-mode")

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_started_services() == []

        mock_check_output.assert_called_once_with(
            ["docker", "ps", "-q"], stderr=mock.ANY
        )
        mock_run.assert_not_called()


@mock.patch("devservices.utils.docker.subprocess.run")
@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_purge_with_cache_and_state_and_running_containers_confirmed(
    mock_check_output: mock.Mock, mock_run: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", fake_yes_input),
    ):
        # Mock return value for "docker ps -q"
        mock_check_output.return_value = b"container_id"
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.add_started_service("test-service", "test-mode")

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_started_services() == []

        mock_check_output.assert_called_once_with(
            ["docker", "ps", "-q"], stderr=mock.ANY
        )
        mock_run.assert_called_once_with(
            ["docker", "stop", "container_id"],
            check=True,
            stdout=mock.ANY,
            stderr=mock.ANY,
        )


@mock.patch("devservices.utils.docker.subprocess.run")
@mock.patch("devservices.utils.docker.subprocess.check_output")
def test_purge_with_cache_and_state_and_running_containers_not_confirmed(
    mock_check_output: mock.Mock, mock_run: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", fake_no_input),
    ):
        # Mock return value for "docker ps -q"
        mock_check_output.return_value = b"container_id"
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.add_started_service("test-service", "test-mode")

        args = Namespace()
        purge(args)

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        mock_check_output.assert_not_called()
        mock_run.assert_not_called()
