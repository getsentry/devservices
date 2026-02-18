from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.sandbox import _parse_port_specs
from devservices.commands.sandbox import _resolve_sandbox_name
from devservices.commands.sandbox import _wait_for_status
from devservices.commands.sandbox import add_parser
from devservices.commands.sandbox import sandbox_create
from devservices.commands.sandbox import sandbox_destroy
from devservices.commands.sandbox import sandbox_list
from devservices.commands.sandbox import sandbox_port_forward
from devservices.commands.sandbox import sandbox_ssh
from devservices.commands.sandbox import sandbox_exec
from devservices.commands.sandbox import sandbox_migrate
from devservices.commands.sandbox import sandbox_restart_devserver
from devservices.commands.sandbox import sandbox_ssh_config
from devservices.commands.sandbox import sandbox_start
from devservices.commands.sandbox import sandbox_status
from devservices.commands.sandbox import sandbox_stop
from devservices.commands.sandbox import sandbox_sync
from devservices.constants import SANDBOX_DEFAULT_MACHINE_TYPE
from devservices.constants import SANDBOX_DEFAULT_ZONE
from devservices.constants import SANDBOX_MAINTENANCE_SYNC_PATH
from devservices.constants import SANDBOX_PORT_PROFILES
from devservices.exceptions import SandboxError
from devservices.exceptions import SandboxOperationError
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
    assert args.ports is None
    assert args.no_forward is False


def test_add_parser_ssh_with_ports_and_no_forward() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "ssh", "--ports", "8000,8010", "--no-forward"])
    assert args.ports == "8000,8010"
    assert args.no_forward is True


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


# --- _parse_port_specs tests ---


def test_parse_port_specs_none_returns_defaults() -> None:
    result = _parse_port_specs(None)
    assert result == [(8000, 8000)]


def test_parse_port_specs_single_port() -> None:
    result = _parse_port_specs("8000")
    assert result == [(8000, 8000)]


def test_parse_port_specs_multiple_same_ports() -> None:
    result = _parse_port_specs("8000,5432")
    assert result == [(8000, 8000), (5432, 5432)]


def test_parse_port_specs_custom_mapping() -> None:
    result = _parse_port_specs("15432:5432")
    assert result == [(15432, 5432)]


def test_parse_port_specs_mixed() -> None:
    result = _parse_port_specs("8000,15432:5432,16379:6379")
    assert result == [(8000, 8000), (15432, 5432), (16379, 6379)]


def test_parse_port_specs_with_spaces() -> None:
    result = _parse_port_specs("8000, 15432:5432")
    assert result == [(8000, 8000), (15432, 5432)]


def test_parse_port_specs_profile_devserver() -> None:
    result = _parse_port_specs("devserver")
    assert result == [(8000, 8000)]


def test_parse_port_specs_profile_services() -> None:
    result = _parse_port_specs("services")
    assert result == SANDBOX_PORT_PROFILES["services"]
    assert len(result) == 7


def test_parse_port_specs_profile_all() -> None:
    result = _parse_port_specs("all")
    assert result == SANDBOX_PORT_PROFILES["all"]
    assert len(result) == 8


def test_parse_port_specs_numeric_ports_still_work() -> None:
    result = _parse_port_specs("8000,5432")
    assert result == [(8000, 8000), (5432, 5432)]


def test_parse_port_specs_custom_mapping_still_works() -> None:
    result = _parse_port_specs("15432:5432")
    assert result == [(15432, 5432)]


def test_parse_port_specs_invalid_profile_raises() -> None:
    with pytest.raises(ValueError):
        _parse_port_specs("nonexistent")


# --- sandbox_create tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=True)
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
    mock_validate_apis: mock.Mock,
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
            sentry_ref=None,
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
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=True)
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
def test_sandbox_create_already_exists(
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_validate_apis: mock.Mock,
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
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=True)
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
    mock_validate_apis: mock.Mock,
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
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=True)
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
    mock_validate_apis: mock.Mock,
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
            sentry_ref=None,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            no_forward=False,
        )
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, ports=[(8000, 8000)]
        )
        captured = capsys.readouterr()
        assert "Connecting to sandbox" in captured.out
        assert "Forwarding port 8000" in captured.out


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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            no_forward=False,
        )
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            no_forward=False,
        )
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
        args = Namespace(
            name=None,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            no_forward=False,
        )
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-recent", "test-project", SANDBOX_DEFAULT_ZONE, ports=[(8000, 8000)]
        )


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_exec")
def test_sandbox_ssh_with_custom_ports(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports="8000,8010,7999",
            no_forward=False,
        )
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            ports=[(8000, 8000), (8010, 8010), (7999, 7999)],
        )
        captured = capsys.readouterr()
        assert "Forwarding port 8000" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_exec")
def test_sandbox_ssh_with_no_forward(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            no_forward=True,
        )
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, ports=None
        )
        captured = capsys.readouterr()
        assert "Forwarding ports" not in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_exec")
def test_sandbox_ssh_no_forward_overrides_ports(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports="8000,9001",
            no_forward=True,
        )
        sandbox_ssh(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, ports=None
        )
        captured = capsys.readouterr()
        assert "Forwarding ports" not in captured.out


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


# --- sandbox_sync tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_sync_basic(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="Updated to latest\n")
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
        sandbox_sync(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            f"{SANDBOX_MAINTENANCE_SYNC_PATH} master",
        )
        captured = capsys.readouterr()
        assert "synced successfully" in captured.out
        assert "Updated to latest" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_sync_not_running(
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
            sandbox_sync(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        assert "Start it first" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_sync_not_found(
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
            sandbox_sync(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch(
    "devservices.commands.sandbox.ssh_command",
    side_effect=SandboxOperationError("ssh", 1, "connection refused"),
)
def test_sandbox_sync_ssh_error(
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
        with pytest.raises(SystemExit):
            sandbox_sync(args)

        captured = capsys.readouterr()
        assert "Failed to sync sandbox" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_sync_default_name(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="")
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
        sandbox_sync(args)

        mock_ssh.assert_called_once_with(
            "sandbox-recent",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            f"{SANDBOX_MAINTENANCE_SYNC_PATH} master",
        )


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_sync_custom_branch(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="")
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "feature-x",
            "default",
        )
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            sentry_ref=None,
        )
        sandbox_sync(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            f"{SANDBOX_MAINTENANCE_SYNC_PATH} feature-x",
        )
        captured = capsys.readouterr()
        assert "feature-x" in captured.out
        assert "synced successfully" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_sync_with_sentry_ref(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="")
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            sentry_ref="feat/my-sentry-branch",
        )
        sandbox_sync(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            f"{SANDBOX_MAINTENANCE_SYNC_PATH} master feat/my-sentry-branch",
        )
        captured = capsys.readouterr()
        assert "sentry: feat/my-sentry-branch" in captured.out
        assert "synced successfully" in captured.out


# --- sandbox_status tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details")
def test_sandbox_status_running(
    mock_details: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_details.return_value = {
        "name": "sandbox-test",
        "status": "RUNNING",
        "zone": "us-central1-a",
        "machine_type": "e2-standard-8",
        "branch": "master",
        "mode": "default",
        "internal_ip": "10.128.0.5",
        "created": "2025-01-15T10:00:00Z",
    }
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
        sandbox_status(args)

        captured = capsys.readouterr()
        assert "sandbox-test" in captured.out
        assert "RUNNING" in captured.out
        assert "us-central1-a" in captured.out
        assert "e2-standard-8" in captured.out
        assert "master" in captured.out
        assert "10.128.0.5" in captured.out
        assert "devservices sandbox ssh" in captured.out
        assert "devservices sandbox sync" in captured.out
        assert "devservices sandbox port-forward" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details")
def test_sandbox_status_stopped(
    mock_details: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_details.return_value = {
        "name": "sandbox-test",
        "status": "TERMINATED",
        "zone": "us-central1-a",
        "machine_type": "e2-standard-8",
        "branch": "master",
        "mode": "default",
        "internal_ip": "N/A",
        "created": "2025-01-15T10:00:00Z",
    }
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
        sandbox_status(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        # Should not show connect/sync/forward hints for non-RUNNING
        assert "devservices sandbox ssh" not in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details", return_value=None)
def test_sandbox_status_not_found(
    mock_details: mock.Mock,
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
            sandbox_status(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
def test_sandbox_status_with_port_forward(
    mock_pf_running: mock.Mock,
    mock_details: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_details.return_value = {
        "name": "sandbox-test",
        "status": "RUNNING",
        "zone": "us-central1-a",
        "machine_type": "e2-standard-8",
        "branch": "master",
        "mode": "default",
        "internal_ip": "10.128.0.5",
        "created": "2025-01-15T10:00:00Z",
    }
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
        state.update_port_forward_pid("sandbox-test", 12345)
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_status(args)

        captured = capsys.readouterr()
        assert "Port Forward: Active (PID 12345)" in captured.out
        mock_pf_running.assert_called_once_with(12345)


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=False)
def test_sandbox_status_stale_port_forward(
    mock_pf_running: mock.Mock,
    mock_details: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_details.return_value = {
        "name": "sandbox-test",
        "status": "RUNNING",
        "zone": "us-central1-a",
        "machine_type": "e2-standard-8",
        "branch": "master",
        "mode": "default",
        "internal_ip": "10.128.0.5",
        "created": "2025-01-15T10:00:00Z",
    }
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
        state.update_port_forward_pid("sandbox-test", 99999)
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_status(args)

        captured = capsys.readouterr()
        assert "Port Forward: Stale (PID 99999 not running)" in captured.out

        # Verify PID was cleaned up in state
        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["port_forward_pid"] is None


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_details")
def test_sandbox_status_default_name(
    mock_details: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_details.return_value = {
        "name": "sandbox-recent",
        "status": "RUNNING",
        "zone": "us-central1-a",
        "machine_type": "e2-standard-8",
        "branch": "master",
        "mode": "default",
        "internal_ip": "10.128.0.5",
        "created": "2025-01-15T10:00:00Z",
    }
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
        sandbox_status(args)

        mock_details.assert_called_once_with(
            "sandbox-recent", "test-project", SANDBOX_DEFAULT_ZONE
        )
        captured = capsys.readouterr()
        assert "sandbox-recent" in captured.out


# --- sandbox_port_forward tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.start_port_forward")
def test_sandbox_port_forward_basic(
    mock_start_pf: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_proc = mock.Mock()
    mock_proc.pid = 12345
    mock_start_pf.return_value = mock_proc
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=False,
        )
        sandbox_port_forward(args)

        mock_start_pf.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, [(8000, 8000)]
        )
        captured = capsys.readouterr()
        assert "Port forwarding active (PID 12345)" in captured.out
        assert "http://localhost:8000" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["port_forward_pid"] == "12345"


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.start_port_forward")
def test_sandbox_port_forward_custom_ports(
    mock_start_pf: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_proc = mock.Mock()
    mock_proc.pid = 54321
    mock_start_pf.return_value = mock_proc
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports="8000,8001",
            stop=False,
        )
        sandbox_port_forward(args)

        mock_start_pf.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, [(8000, 8000), (8001, 8001)]
        )
        captured = capsys.readouterr()
        assert "Port forwarding active (PID 54321)" in captured.out
        assert "http://localhost:8000" in captured.out
        assert "http://localhost:8001" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
@mock.patch("devservices.commands.sandbox.stop_port_forward")
def test_sandbox_port_forward_stop(
    mock_stop_pf: mock.Mock,
    mock_pf_running: mock.Mock,
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
        state.update_port_forward_pid("sandbox-test", 12345)
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=True,
        )
        sandbox_port_forward(args)

        mock_stop_pf.assert_called_once_with(12345)
        captured = capsys.readouterr()
        assert "Port forwarding stopped (PID 12345)" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["port_forward_pid"] is None


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
def test_sandbox_port_forward_stop_no_tunnel(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=True,
        )
        sandbox_port_forward(args)

        captured = capsys.readouterr()
        assert "No active port forwarding" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
def test_sandbox_port_forward_already_running(
    mock_pf_running: mock.Mock,
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
        state.update_port_forward_pid("sandbox-test", 99999)
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=False,
        )
        sandbox_port_forward(args)

        captured = capsys.readouterr()
        assert "Port forwarding already active (PID 99999)" in captured.out
        assert "Use --stop to stop it first" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_port_forward_not_running(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=False,
        )
        with pytest.raises(SystemExit):
            sandbox_port_forward(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        assert "Start it first" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_port_forward_not_found(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            stop=False,
        )
        with pytest.raises(SystemExit):
            sandbox_port_forward(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


# --- stop/destroy port-forward cleanup tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.stop_instance")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
@mock.patch("devservices.commands.sandbox.stop_port_forward")
def test_sandbox_stop_kills_port_forward(
    mock_stop_pf: mock.Mock,
    mock_pf_running: mock.Mock,
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
        state.update_port_forward_pid("sandbox-test", 12345)
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_stop(args)

        mock_stop_pf.assert_called_once_with(12345)
        captured = capsys.readouterr()
        assert "Port forwarding stopped (PID 12345)" in captured.out

        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["port_forward_pid"] is None


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.delete_instance")
@mock.patch("devservices.commands.sandbox.Console.confirm", return_value=True)
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
@mock.patch("devservices.commands.sandbox.stop_port_forward")
def test_sandbox_destroy_kills_port_forward(
    mock_stop_pf: mock.Mock,
    mock_pf_running: mock.Mock,
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
        state.update_port_forward_pid("sandbox-test", 12345)
        args = Namespace(name="sandbox-test", project=None, zone=SANDBOX_DEFAULT_ZONE)
        sandbox_destroy(args)

        mock_stop_pf.assert_called_once_with(12345)
        mock_delete.assert_called_once()
        captured = capsys.readouterr()
        assert "Port forwarding stopped (PID 12345)" in captured.out


# --- sandbox_create API validation tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=False)
def test_sandbox_create_missing_apis(
    mock_validate_apis: mock.Mock,
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

        mock_validate_apis.assert_called_once_with("test-project", mock.ANY)


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.validate_sandbox_apis", return_value=True)
@mock.patch(
    "devservices.commands.sandbox.generate_instance_name", return_value="sandbox-test"
)
@mock.patch("devservices.commands.sandbox.get_instance_status")
@mock.patch("devservices.commands.sandbox.create_instance")
@mock.patch("devservices.commands.sandbox.time.sleep")
def test_sandbox_create_apis_valid(
    mock_sleep: mock.Mock,
    mock_create: mock.Mock,
    mock_get_status: mock.Mock,
    mock_gen_name: mock.Mock,
    mock_validate_apis: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
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

        mock_validate_apis.assert_called_once_with("test-project", mock.ANY)
        mock_create.assert_called_once()
        captured = capsys.readouterr()
        assert "created successfully" in captured.out


# --- sandbox_ssh_config parser tests ---


def test_ssh_config_parser_registered() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "ssh-config"])
    assert args.sandbox_command == "ssh-config"
    assert args.name is None
    assert args.ports is None
    assert args.append is False
    assert args.remove is False
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE


def test_ssh_config_parser_all_args() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(
        [
            "sandbox",
            "ssh-config",
            "my-sandbox",
            "--ports",
            "8000,15432:5432",
            "--append",
            "--project",
            "my-project",
            "--zone",
            "us-east1-b",
        ]
    )
    assert args.name == "my-sandbox"
    assert args.ports == "8000,15432:5432"
    assert args.append is True
    assert args.project == "my-project"
    assert args.zone == "us-east1-b"


# --- sandbox_ssh_config handler tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch(
    "devservices.commands.sandbox.generate_ssh_config",
    return_value="# BEGIN devservices-sandbox: sandbox-test\nHost sandbox-test\n# END devservices-sandbox: sandbox-test\n",
)
def test_sandbox_ssh_config_print_to_stdout(
    mock_gen_config: mock.Mock,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            append=False,
            remove=False,
        )
        sandbox_ssh_config(args)

        mock_gen_config.assert_called_once_with(
            "sandbox-test", "test-project", SANDBOX_DEFAULT_ZONE, None
        )
        captured = capsys.readouterr()
        assert "Host sandbox-test" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch(
    "devservices.commands.sandbox.generate_ssh_config",
    return_value="# BEGIN devservices-sandbox: sandbox-test\nHost sandbox-test\n# END devservices-sandbox: sandbox-test\n",
)
@mock.patch("devservices.commands.sandbox.write_ssh_config_entry")
@mock.patch(
    "devservices.commands.sandbox.get_ssh_config_path",
    return_value="/home/user/.ssh/config",
)
def test_sandbox_ssh_config_append(
    mock_get_path: mock.Mock,
    mock_write: mock.Mock,
    mock_gen_config: mock.Mock,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            append=True,
            remove=False,
        )
        sandbox_ssh_config(args)

        mock_write.assert_called_once_with(
            "/home/user/.ssh/config",
            "sandbox-test",
            mock_gen_config.return_value,
        )
        captured = capsys.readouterr()
        assert "SSH config entry written" in captured.out
        assert "ssh sandbox-test" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.remove_ssh_config_entry", return_value=True
)
@mock.patch(
    "devservices.commands.sandbox.get_ssh_config_path",
    return_value="/home/user/.ssh/config",
)
def test_sandbox_ssh_config_remove(
    mock_get_path: mock.Mock,
    mock_remove: mock.Mock,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            append=False,
            remove=True,
        )
        sandbox_ssh_config(args)

        mock_remove.assert_called_once_with(
            "/home/user/.ssh/config", "sandbox-test"
        )
        captured = capsys.readouterr()
        assert "Removed SSH config entry" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.remove_ssh_config_entry", return_value=False
)
@mock.patch(
    "devservices.commands.sandbox.get_ssh_config_path",
    return_value="/home/user/.ssh/config",
)
def test_sandbox_ssh_config_remove_not_found(
    mock_get_path: mock.Mock,
    mock_remove: mock.Mock,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            append=False,
            remove=True,
        )
        sandbox_ssh_config(args)

        captured = capsys.readouterr()
        assert "No SSH config entry found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_ssh_config_instance_not_found(
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports=None,
            append=False,
            remove=False,
        )
        with pytest.raises(SystemExit):
            sandbox_ssh_config(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.generate_ssh_config", return_value="config block\n")
def test_sandbox_ssh_config_with_ports(
    mock_gen_config: mock.Mock,
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
        args = Namespace(
            name="sandbox-test",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
            ports="8000,15432:5432",
            append=False,
            remove=False,
        )
        sandbox_ssh_config(args)

        mock_gen_config.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            [(8000, 8000), (15432, 5432)],
        )


# --- sandbox_migrate parser tests ---


def test_migrate_parser_registered() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "migrate"])
    assert args.sandbox_command == "migrate"
    assert args.name is None
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE


# --- sandbox_restart_devserver parser tests ---


def test_restart_devserver_parser_registered() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "restart-devserver"])
    assert args.sandbox_command == "restart-devserver"
    assert args.name is None
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE


# --- sandbox_exec parser tests ---


def test_exec_parser_registered() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)

    args = parser.parse_args(["sandbox", "exec", "ls -la"])
    assert args.sandbox_command == "exec"
    assert args.command == "ls -la"
    assert args.name is None
    assert args.project is None
    assert args.zone == SANDBOX_DEFAULT_ZONE

    # --name option
    args_named = parser.parse_args(
        ["sandbox", "exec", "--name", "my-sandbox", "uptime"]
    )
    assert args_named.name == "my-sandbox"
    assert args_named.command == "uptime"


# --- sandbox_migrate handler tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_migrate_success(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="Running migrations...\nApplied 3 migrations\n")
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
        sandbox_migrate(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "cd /opt/getsentry && make apply-migrations",
        )
        captured = capsys.readouterr()
        assert "Running migrations" in captured.out
        assert "Applied 3 migrations" in captured.out
        assert "Migrations completed successfully" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_migrate_instance_not_running(
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
            sandbox_migrate(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        assert "Start it first" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_migrate_instance_not_found(
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
            sandbox_migrate(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


# --- sandbox_restart_devserver handler tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_restart_devserver_success(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.side_effect = [
        mock.Mock(stdout="", stderr=""),  # restart call
        mock.Mock(stdout="active\n", stderr=""),  # is-active call
    ]
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
        sandbox_restart_devserver(args)

        assert mock_ssh.call_count == 2
        mock_ssh.assert_any_call(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "sudo systemctl restart sandbox-devserver",
        )
        mock_ssh.assert_any_call(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "sudo systemctl is-active sandbox-devserver",
        )
        captured = capsys.readouterr()
        assert "Devserver restarted" in captured.out
        assert "active" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch(
    "devservices.commands.sandbox.get_instance_status", return_value="TERMINATED"
)
def test_sandbox_restart_devserver_not_running(
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
            sandbox_restart_devserver(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
        assert "Start it first" in captured.out


# --- sandbox_exec handler tests ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_exec_success(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="file1.txt\nfile2.txt\n", stderr="")
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
        args = Namespace(
            name="sandbox-test",
            command="ls -la",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        sandbox_exec(args)

        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "ls -la",
        )
        captured = capsys.readouterr()
        assert "file1.txt" in captured.out
        assert "file2.txt" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_exec_with_name(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(stdout="ok\n", stderr="")
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-custom",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            SANDBOX_DEFAULT_MACHINE_TYPE,
            "master",
            "default",
        )
        args = Namespace(
            name="custom",
            command="uptime",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        sandbox_exec(args)

        mock_ssh.assert_called_once_with(
            "sandbox-custom",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "uptime",
        )
        captured = capsys.readouterr()
        assert "ok" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
def test_sandbox_exec_with_stderr(
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_ssh.return_value = mock.Mock(
        stdout="partial output\n", stderr="Warning: something happened"
    )
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
        args = Namespace(
            name="sandbox-test",
            command="some-cmd",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        sandbox_exec(args)

        captured = capsys.readouterr()
        assert "partial output" in captured.out
        assert "Warning: something happened" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value=None)
def test_sandbox_exec_not_found(
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
        args = Namespace(
            name="sandbox-test",
            command="ls",
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        with pytest.raises(SystemExit):
            sandbox_exec(args)

        captured = capsys.readouterr()
        assert "not found" in captured.out


# --- sandbox_hybrid ---


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
@mock.patch("devservices.commands.sandbox.start_port_forward")
def test_sandbox_hybrid_start(
    mock_start_pf: mock.Mock,
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from devservices.commands.sandbox import sandbox_hybrid

    mock_proc = mock.MagicMock()
    mock_proc.pid = 99999
    mock_start_pf.return_value = mock_proc

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
        args = Namespace(
            name="sandbox-test",
            stop=False,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        sandbox_hybrid(args)

        # Verify devserver was stopped
        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "sudo systemctl stop sandbox-devserver",
        )
        # Verify port forwarding started with service ports
        mock_start_pf.assert_called_once()
        call_ports = mock_start_pf.call_args[0][3]
        assert (5432, 5432) in call_ports
        assert (6379, 6379) in call_ports

        captured = capsys.readouterr()
        assert "Hybrid mode active" in captured.out
        assert "devservices serve" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="RUNNING")
@mock.patch("devservices.commands.sandbox.ssh_command")
@mock.patch("devservices.commands.sandbox.is_port_forward_running", return_value=True)
@mock.patch("devservices.commands.sandbox.stop_port_forward")
def test_sandbox_hybrid_stop(
    mock_stop_pf: mock.Mock,
    mock_is_running: mock.Mock,
    mock_ssh: mock.Mock,
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from devservices.commands.sandbox import sandbox_hybrid

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
        state.update_port_forward_pid("sandbox-test", 12345)
        args = Namespace(
            name="sandbox-test",
            stop=True,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        sandbox_hybrid(args)

        # Verify devserver was restarted
        mock_ssh.assert_called_once_with(
            "sandbox-test",
            "test-project",
            SANDBOX_DEFAULT_ZONE,
            "sudo systemctl start sandbox-devserver",
        )
        # Verify port forwarding was stopped
        mock_stop_pf.assert_called_once_with(12345)

        captured = capsys.readouterr()
        assert "Hybrid mode stopped" in captured.out


@mock.patch("devservices.commands.sandbox.validate_sandbox_prerequisites")
@mock.patch("devservices.commands.sandbox.resolve_project", return_value="test-project")
@mock.patch("devservices.commands.sandbox.get_instance_status", return_value="TERMINATED")
def test_sandbox_hybrid_not_running(
    mock_get_status: mock.Mock,
    mock_resolve: mock.Mock,
    mock_validate: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from devservices.commands.sandbox import sandbox_hybrid

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
        args = Namespace(
            name="sandbox-test",
            stop=False,
            project=None,
            zone=SANDBOX_DEFAULT_ZONE,
        )
        with pytest.raises(SystemExit):
            sandbox_hybrid(args)

        captured = capsys.readouterr()
        assert "TERMINATED" in captured.out
