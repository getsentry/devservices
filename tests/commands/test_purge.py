from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.purge import purge
from devservices.constants import DEVSERVICES_ORCHESTRATOR_LABEL
from devservices.constants import DOCKER_NETWORK_NAME
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.exceptions import DockerError
from devservices.utils.state import State
from devservices.utils.state import StateTables


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_daemon_not_running(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.side_effect = DockerDaemonNotRunningError()
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_not_called()
        mock_stop_containers.assert_not_called()
        mock_remove_docker_resources.assert_not_called()

        captured = capsys.readouterr()
        assert (
            "Unable to connect to the docker daemon. Is the docker daemon running?"
            in captured.out.strip()
        )


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_error_get_matching_containers(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.side_effect = DockerError(
        "command", 1, "output", "stderr"
    )
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        with pytest.raises(SystemExit):
            purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_not_called()
        mock_stop_containers.assert_not_called()
        mock_remove_docker_resources.assert_not_called()

        captured = capsys.readouterr()
        assert "Failed to get devservices containers stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_error_get_volumes_for_containers(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghi"]
    mock_get_volumes_for_containers.side_effect = DockerError(
        "command", 1, "output", "stderr"
    )
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        with pytest.raises(SystemExit):
            purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_called_once_with(["abc", "def", "ghi"])
        mock_stop_containers.assert_not_called()
        mock_remove_docker_resources.assert_not_called()

        captured = capsys.readouterr()
        assert "Failed to get devservices volumes stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.get_matching_networks")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_error_get_matching_networks(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_matching_networks: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghi"]
    mock_get_volumes_for_containers.return_value = ["jkl", "mno", "pqr"]
    mock_get_matching_networks.side_effect = DockerError(
        "command", 1, "output", "stderr"
    )
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        with pytest.raises(SystemExit):
            purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_called_once_with(["abc", "def", "ghi"])
        mock_stop_containers.assert_called_once_with(
            ["abc", "def", "ghi"], should_remove=True
        )
        mock_get_matching_networks.assert_called_once_with(DOCKER_NETWORK_NAME)
        mock_remove_docker_resources.assert_called_once_with(
            "volume", ["jkl", "mno", "pqr"]
        )

        captured = capsys.readouterr()
        assert "Failed to get devservices networks stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
def test_purge_docker_error_stop_containers(
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghi"]
    mock_get_volumes_for_containers.return_value = ["jkl", "mno", "pqr"]
    mock_stop_containers.side_effect = DockerError("command", 1, "output", "stderr")
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        with pytest.raises(SystemExit):
            purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_called_once_with(["abc", "def", "ghi"])
        mock_stop_containers.assert_called_once_with(
            ["abc", "def", "ghi"], should_remove=True
        )

        captured = capsys.readouterr()
        assert "Failed to stop devservices containers stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.get_matching_networks")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_error_remove_volumes_continues_to_remove_networks(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_matching_networks: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghi"]
    mock_get_volumes_for_containers.return_value = ["jkl", "mno", "pqr"]
    mock_get_matching_networks.return_value = ["devservices"]
    mock_remove_docker_resources.side_effect = [
        DockerError("command", 1, "output", "stderr"),
        None,
    ]
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_called_once_with(["abc", "def", "ghi"])
        mock_stop_containers.assert_called_once_with(
            ["abc", "def", "ghi"], should_remove=True
        )
        mock_get_matching_networks.assert_called_once_with(DOCKER_NETWORK_NAME)
        mock_remove_docker_resources.assert_has_calls(
            [
                mock.call("volume", ["jkl", "mno", "pqr"]),
                mock.call("network", ["devservices"]),
            ]
        )

        captured = capsys.readouterr()
        assert "Failed to remove devservices volumes stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.get_matching_networks")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_docker_error_remove_networks(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_matching_networks: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghi"]
    mock_get_volumes_for_containers.return_value = ["jkl", "mno", "pqr"]
    mock_get_matching_networks.return_value = ["devservices"]
    mock_remove_docker_resources.side_effect = [
        None,
        DockerError("command", 1, "output", "stderr"),
    ]
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        # Create a cache file to test purging
        cache_dir = tmp_path / ".devservices-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = tmp_path / ".devservices-cache" / "test.txt"
        cache_file.write_text("This is a test cache file.")

        state = State()
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        with pytest.raises(SystemExit):
            purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_get_matching_containers.assert_called_once_with(
            DEVSERVICES_ORCHESTRATOR_LABEL
        )
        mock_get_volumes_for_containers.assert_called_once_with(["abc", "def", "ghi"])
        mock_stop_containers.assert_called_once_with(
            ["abc", "def", "ghi"], should_remove=True
        )
        mock_get_matching_networks.assert_called_once_with(DOCKER_NETWORK_NAME)
        mock_remove_docker_resources.assert_has_calls(
            [
                mock.call("volume", ["jkl", "mno", "pqr"]),
                mock.call("network", ["devservices"]),
            ]
        )

        captured = capsys.readouterr()
        assert "Failed to remove devservices networks stderr" in captured.out.strip()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_matching_networks")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_with_cache_and_state_and_no_containers(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_networks: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = []
    mock_get_volumes_for_containers.return_value = []
    mock_get_matching_networks.return_value = []
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
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
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_stop_containers.assert_called_once_with([], should_remove=True)
        mock_remove_docker_resources.assert_not_called()


@mock.patch("devservices.commands.purge.get_matching_containers")
@mock.patch("devservices.commands.purge.get_matching_networks")
@mock.patch("devservices.commands.purge.get_volumes_for_containers")
@mock.patch("devservices.commands.purge.stop_containers")
@mock.patch("devservices.commands.purge.remove_docker_resources")
def test_purge_with_cache_and_state_and_containers_with_networks_and_volumes(
    mock_remove_docker_resources: mock.Mock,
    mock_stop_containers: mock.Mock,
    mock_get_volumes_for_containers: mock.Mock,
    mock_get_matching_networks: mock.Mock,
    mock_get_matching_containers: mock.Mock,
    tmp_path: Path,
) -> None:
    mock_get_matching_containers.return_value = ["abc", "def", "ghe"]
    mock_get_volumes_for_containers.return_value = ["jkl", "mno", "pqr"]
    mock_get_matching_networks.return_value = ["abc", "def", "ghe"]
    with (
        mock.patch(
            "devservices.commands.purge.DEVSERVICES_CACHE_DIR",
            str(tmp_path / ".devservices-cache"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
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
        state.update_service_entry(
            "test-service", "test-mode", StateTables.STARTED_SERVICES
        )

        assert cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "test-service"
        ]

        args = Namespace()
        purge(args)

        assert not cache_file.exists()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []

        mock_stop_containers.assert_called_once_with(
            ["abc", "def", "ghe"], should_remove=True
        )
        mock_remove_docker_resources.assert_has_calls(
            [
                mock.call("volume", ["jkl", "mno", "pqr"]),
                mock.call("network", ["abc", "def", "ghe"]),
            ]
        )
