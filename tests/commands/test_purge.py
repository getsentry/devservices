from __future__ import annotations

import builtins
from argparse import Namespace
from pathlib import Path
from unittest import mock

from devservices.commands.purge import purge
from devservices.utils.state import State


@mock.patch("devservices.commands.purge.stop_all_running_containers")
def test_purge_not_confirmed(
    mock_stop_all_running_containers: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", lambda _: "no"),
    ):
        args = Namespace()
        purge(args)

        mock_stop_all_running_containers.assert_not_called()


@mock.patch("devservices.commands.purge.stop_all_running_containers")
@mock.patch("devservices.commands.purge.subprocess.run")
def test_purge_with_cache_and_state_and_no_running_containers_confirmed(
    mock_run: mock.Mock, mock_stop_all_running_containers: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", lambda _: "yes"),
        mock.patch(
            "devservices.utils.docker.check_docker_daemon_running", return_value=None
        ),
        mock.patch(
            "devservices.commands.purge.subprocess.check_output",
            return_value=b"",
        ),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_started_service("test-service", "test-mode")

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_started_services() == []

        mock_stop_all_running_containers.assert_called_once()
        mock_run.assert_not_called()


@mock.patch("devservices.commands.purge.stop_all_running_containers")
@mock.patch("devservices.commands.purge.subprocess.run")
def test_purge_with_cache_and_state_and_running_containers_with_networks_confirmed(
    mock_run: mock.Mock, mock_stop_all_running_containers: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", lambda _: "yes"),
        mock.patch(
            "devservices.utils.docker.check_docker_daemon_running", return_value=None
        ),
        mock.patch(
            "devservices.commands.purge.subprocess.check_output",
            return_value=b"abc\ndef\nghe\n",
        ),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_started_service("test-service", "test-mode")

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_started_services() == []

        mock_run.assert_has_calls(
            [
                mock.call(
                    ["docker", "network", "rm", "abc"],
                    check=True,
                    stdout=mock.ANY,
                    stderr=mock.ANY,
                ),
                mock.call(
                    ["docker", "network", "rm", "def"],
                    check=True,
                    stdout=mock.ANY,
                    stderr=mock.ANY,
                ),
                mock.call(
                    ["docker", "network", "rm", "ghe"],
                    check=True,
                    stdout=mock.ANY,
                    stderr=mock.ANY,
                ),
            ]
        )
        mock_stop_all_running_containers.assert_called_once()


@mock.patch("devservices.commands.purge.stop_all_running_containers")
@mock.patch("devservices.commands.purge.subprocess.run")
def test_purge_with_cache_and_state_and_running_containers_not_confirmed(
    mock_run: mock.Mock, mock_stop_all_running_containers: mock.Mock, tmp_path: Path
) -> None:
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch.object(builtins, "input", lambda _: "no"),
        mock.patch(
            "devservices.utils.docker.check_docker_daemon_running", return_value=None
        ),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_started_service("test-service", "test-mode")

        args = Namespace()
        purge(args)

        assert cache_file.exists()
        assert state.get_started_services() == ["test-service"]

        mock_run.assert_not_called()
        mock_stop_all_running_containers.assert_not_called()
