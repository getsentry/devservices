from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.sandbox import _resolve_sandbox_name
from devservices.commands.sandbox import _wait_for_status
from devservices.commands.sandbox import add_parser
from devservices.commands.sandbox import sandbox_create
from devservices.commands.sandbox import sandbox_destroy
from devservices.commands.sandbox import sandbox_list
from devservices.commands.sandbox import sandbox_ssh
from devservices.commands.sandbox import sandbox_start
from devservices.commands.sandbox import sandbox_stop
from devservices.constants import SANDBOX_DEFAULT_MACHINE_TYPE
from devservices.constants import SANDBOX_DEFAULT_ZONE
from devservices.exceptions import SandboxError
from devservices.utils.console import Console
from devservices.utils.state import State


# --- Parser tests ---


def test_add_parser_registers_sandbox_command() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox"])
    assert args.command == "sandbox"


def test_add_parser_create_defaults() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "create"])
    assert args.sandbox_command == "create"
    assert args.name is None
    assert args.branch == "master"
    assert args.mode == "default"
    assert args.machine_type == SANDBOX_DEFAULT_MACHINE_TYPE
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE
    assert args.spot is False


def test_add_parser_create_custom_args() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(
        [
            "sandbox",
            "create",
            "my-sandbox",
            "--branch",
            "feature-branch",
            "--mode",
            "heavy",
            "--machine-type",
            "n1-standard-16",
            "--project",
            "my-project",
            "--zone",
            "us-east1-b",
            "--spot",
        ]
    )
    assert args.name == "my-sandbox"
    assert args.branch == "feature-branch"
    assert args.mode == "heavy"
    assert args.machine_type == "n1-standard-16"
    assert args.project == "my-project"
    assert args.zone == "us-east1-b"
    assert args.spot is True


def test_add_parser_ssh_defaults() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "ssh"])
    assert args.sandbox_command == "ssh"
    assert args.name is None
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE


def test_add_parser_list_defaults() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "list"])
    assert args.sandbox_command == "list"
    assert args.project is None
    assert args.zone is None


# --- _resolve_sandbox_name tests ---


def test_resolve_sandbox_name_from_args(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        console = Console()
        args = Namespace(name="my-sandbox")
        result = _resolve_sandbox_name(args, state, console)
        assert result == "sandbox-my-sandbox"


def test_resolve_sandbox_name_from_args_already_prefixed(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        console = Console()
        args = Namespace(name="sandbox-my-sandbox")
        result = _resolve_sandbox_name(args, state, console)
        assert result == "sandbox-my-sandbox"


def test_resolve_sandbox_name_default_from_state(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-recent",
            "test-project",
            "us-central1-a",
            "e2-standard-8",
            "master",
            "default",
        )
        console = Console()
        args = Namespace(name=None)
        result = _resolve_sandbox_name(args, state, console)
        assert result == "sandbox-recent"


def test_resolve_sandbox_name_no_sandbox_exits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        console = Console()
        args = Namespace(name=None)
        with pytest.raises(SystemExit):
            _resolve_sandbox_name(args, state, console)
        captured = capsys.readouterr()
        assert "No sandbox name provided" in captured.out


# --- _wait_for_status tests ---


@mock.patch("devservices.commands.sandbox.time.sleep")
@mock.patch("devservices.commands.sandbox.get_instance_status")
def test_wait_for_status_immediate(
    mock_get_status: mock.Mock,
    mock_sleep: mock.Mock,
) -> None:
    mock_get_status.return_value = "RUNNING"
    status = mock.MagicMock()
    result = _wait_for_status("sandbox-test", "proj", "zone", "RUNNING", status)
    assert result is True
    mock_sleep.assert_not_called()


@mock.patch("devservices.commands.sandbox.SANDBOX_STATUS_POLL_TIMEOUT", 15)
@mock.patch("devservices.commands.sandbox.SANDBOX_STATUS_POLL_INTERVAL", 5)
@mock.patch("devservices.commands.sandbox.time.sleep")
@mock.patch("devservices.commands.sandbox.get_instance_status")
def test_wait_for_status_eventual(
    mock_get_status: mock.Mock,
    mock_sleep: mock.Mock,
) -> None:
    mock_get_status.side_effect = ["STAGING", "STAGING", "RUNNING"]
    status = mock.MagicMock()
    result = _wait_for_status("sandbox-test", "proj", "zone", "RUNNING", status)
    assert result is True
    assert mock_sleep.call_count == 2


@mock.patch("devservices.commands.sandbox.SANDBOX_STATUS_POLL_TIMEOUT", 10)
@mock.patch("devservices.commands.sandbox.SANDBOX_STATUS_POLL_INTERVAL", 5)
@mock.patch("devservices.commands.sandbox.time.sleep")
@mock.patch("devservices.commands.sandbox.get_instance_status")
def test_wait_for_status_timeout(
    mock_get_status: mock.Mock,
    mock_sleep: mock.Mock,
) -> None:
    mock_get_status.return_value = "STAGING"
    status = mock.MagicMock()
    result = _wait_for_status("sandbox-test", "proj", "zone", "RUNNING", status)
    assert result is False


# --- sandbox_create tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status")
@mock.patch("devservices.commands.sandbox.create_instance")
@mock.patch("devservices.commands.sandbox.time.sleep")
def test_sandbox_create_basic(
    mock_sleep: mock.Mock,
    mock_create: mock.Mock,
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # First call: check existence (None = not found), second call: poll status (RUNNING)
    mock_get_status.side_effect = [None, "RUNNING"]
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(
            name=None,
            branch="master",
            mode="default",
            machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            spot=False,
        )
        sandbox_create(args)

        mock_create.assert_called_once_with(
            name="sandbox-test",
            project="test-project",
            zone=SANDBOX_DEFAULT_ZONE,
            machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
            branch="master",
            mode="default",
            spot=False,
        )

        state = State()
        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["name"] == "sandbox-test"
        assert instance["project"] == "test-project"
        assert instance["status"] == "RUNNING"

        captured = capsys.readouterr()
        assert "created successfully" in captured.out
        assert "devservices sandbox ssh sandbox-test" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
def test_sandbox_create_already_exists(
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(
            name=None,
            branch="master",
            mode="default",
            machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            spot=False,
        )
        with pytest.raises(SystemExit):
            sandbox_create(args)

        captured = capsys.readouterr()
        assert "already exists" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
@mock.patch(
    "devservices.commands.sandbox.create_instance",
    side_effect=SandboxError("gcloud failed"),
)
def test_sandbox_create_gcloud_error(
    mock_create: mock.Mock,
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(
            name=None,
            branch="master",
            mode="default",
            machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            spot=False,
        )
        with pytest.raises(SystemExit):
            sandbox_create(args)

        captured = capsys.readouterr()
        assert "Failed to create sandbox" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status")
@mock.patch("devservices.commands.sandbox.create_instance")
@mock.patch("devservices.commands.sandbox.time.sleep")
def test_sandbox_create_custom_branch_and_spot(
    mock_sleep: mock.Mock,
    mock_create: mock.Mock,
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_get_status.side_effect = [None, "RUNNING"]
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(
            name="custom",
            branch="feature-x",
            mode="heavy",
            machine_type="n1-standard-16",
            project=None,
            zone="us-east1-b",
            spot=True,
        )
        sandbox_create(args)

        mock_create.assert_called_once_with(
            name="sandbox-test",
            project="test-project",
            zone="us-east1-b",
            machine_type="n1-standard-16",
            branch="feature-x",
            mode="heavy",
            spot=True,
        )


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch(
    "devservices.commands.sandbox.resolve_project",
    side_effect=SandboxError("no project"),
)
def test_sandbox_create_no_project(
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(
            name=None,
            branch="master",
            mode="default",
            machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            spot=False,
        )
        with pytest.raises(SystemExit):
            sandbox_create(args)

        captured = capsys.readouterr()
        assert "no project" in captured.out


# --- sandbox_ssh tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_exec")
def test_sandbox_ssh_running(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE
        )
        captured = capsys.readouterr()
        assert "Connecting to sandbox" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_ssh_not_running(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_ssh(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        assert "Start it first" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_ssh_not_found(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_ssh(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_exec")
def test_sandbox_ssh_default_name(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-recent",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        # No name arg - should use default from state
        args = Namespace(name=None, project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-recent", "test-project", SANDBOX_DEFAULT_ZONE
        )


# --- sandbox_stop tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.stop_instance")
def test_sandbox_stop_running(
    mock_stop: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_stop(args)

        mock_stop.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE
        )
        captured = capsys.readouterr()
        assert "stopped" in captured.out
        assert "Disk preserved" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["status"] == "TERMINATED"


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_stop_already_stopped(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_stop(args)

        captured = capsys.readouterr()
        assert "already stopped" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_stop_not_found(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_stop(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch(
    "devservices.commands.sandbox.stop_instance",
    side_effect=SandboxError("stop failed"),
)
def test_sandbox_stop_gcloud_error(
    mock_stop: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_stop(args)

        captured = capsys.readouterr()
        assert "Failed to stop sandbox" in captured.out


# --- sandbox_start tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
@mock.patch("devservices.commands.sandbox.start_instance")
@mock.patch("devservices.commands.sandbox.time.sleep")
@mock.patch("devservices.commands.sandbox._wait_for_status", return_value=True)
def test_sandbox_start_stopped(
    mock_wait: mock.Mock,
    mock_sleep: mock.Mock,
    mock_start: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_start(args)

        mock_start.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE
        )
        captured = capsys.readouterr()
        assert "started" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["status"] == "RUNNING"


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
def test_sandbox_start_already_running(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_start(args)

        captured = capsys.readouterr()
        assert "already running" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_start_not_found(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_start(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
@mock.patch(
    "devservices.commands.sandbox.start_instance",
    side_effect=SandboxError("start failed"),
)
def test_sandbox_start_gcloud_error(
    mock_start: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_start(args)

        captured = capsys.readouterr()
        assert "Failed to start sandbox" in captured.out


# --- sandbox_destroy tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.delete_instance")
@mock.patch("devservices.commands.sandbox.Console.confirm", return_value=True)
def test_sandbox_destroy_confirmed(
    mock_confirm: mock.Mock,
    mock_delete: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_destroy(args)

        mock_delete.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE
        )
        captured = capsys.readouterr()
        assert "destroyed" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is None


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.delete_instance")
@mock.patch("devservices.commands.sandbox.Console.confirm", return_value=False)
def test_sandbox_destroy_cancelled(
    mock_confirm: mock.Mock,
    mock_delete: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_destroy(args)

        mock_delete.assert_not_called()
        captured = capsys.readouterr()
        assert "Destroy cancelled" in captured.out

        # Instance should still exist
        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_destroy_not_found(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_destroy(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch(
    "devservices.commands.sandbox.delete_instance",
    side_effect=SandboxError("delete failed"),
)
@mock.patch("devservices.commands.sandbox.Console.confirm", return_value=True)
def test_sandbox_destroy_gcloud_error(
    mock_confirm: mock.Mock,
    mock_delete: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        with pytest.raises(SystemExit):
            sandbox_destroy(args)

        captured = capsys.readouterr()
        assert "Failed to destroy sandbox" in captured.out


# --- sandbox_list tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.list_instances")
def test_sandbox_list_with_instances(
    mock_list: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_list.return_value = [
        {
            "name": "sandbox-alice-abc123",
            "status": "RUNNING",
            "zone": "us-central1-a",
            "machine_type": "e2-standard-8",
            "branch": "master",
            "created": "2025-01-15T10:00:00Z",
        },
        {
            "name": "sandbox-bob-def456",
            "status": "TERMINATED",
            "zone": "us-central1-a",
            "machine_type": "e2-standard-4",
            "branch": "feature-x",
            "created": "2025-01-14T09:00:00Z",
        },
    ]
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(project=None, zone=None)
        sandbox_list(args)

        captured = capsys.readouterr()
        assert "NAME" in captured.out
        assert "STATUS" in captured.out
        assert "sandbox-alice-abc123" in captured.out
        assert "RUNNING" in captured.out
        assert "sandbox-bob-def456" in captured.out
        assert "TERMINATED" in captured.out
        assert "feature-x" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.list_instances", return_value=[])
def test_sandbox_list_empty(
    mock_list: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        args = Namespace(project=None, zone=None)
        sandbox_list(args)

        captured = capsys.readouterr()
        assert "No sandbox instances found" in captured.out
        assert "devservices sandbox create" in captured.out
