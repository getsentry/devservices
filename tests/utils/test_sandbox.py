from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from devservices.constants import SANDBOX_DEFAULT_MACHINE_TYPE
from devservices.constants import SANDBOX_DEFAULT_ZONE
from devservices.constants import SANDBOX_DISK_SIZE
from devservices.constants import SANDBOX_DISK_TYPE
from devservices.constants import SANDBOX_IMAGE_FAMILY
from devservices.constants import SANDBOX_IMAGE_PROJECT
from devservices.constants import SANDBOX_LABEL_KEY
from devservices.constants import SANDBOX_LABEL_VALUE
from devservices.constants import SANDBOX_NETWORK_TAG
from devservices.constants import SANDBOX_REQUIRED_APIS
from devservices.exceptions import GCloudNotFoundError
from devservices.exceptions import SandboxOperationError
from devservices.utils.sandbox import check_api_enabled
from devservices.utils.sandbox import check_gcloud_installed
from devservices.utils.sandbox import create_instance
from devservices.utils.sandbox import delete_instance
from devservices.utils.sandbox import generate_instance_name
from devservices.utils.sandbox import get_gcloud_account
from devservices.utils.sandbox import get_gcloud_project
from devservices.utils.sandbox import get_instance_details
from devservices.utils.sandbox import get_instance_status
from devservices.utils.sandbox import is_port_forward_running
from devservices.utils.sandbox import list_instances
from devservices.utils.sandbox import resolve_project
from devservices.utils.sandbox import run_gcloud
from devservices.utils.sandbox import ssh_command
from devservices.utils.sandbox import ssh_exec
from devservices.utils.sandbox import start_instance
from devservices.utils.sandbox import start_port_forward
from devservices.utils.sandbox import stop_instance
from devservices.utils.sandbox import stop_port_forward
from devservices.utils.sandbox import validate_sandbox_apis
from devservices.utils.sandbox import validate_sandbox_prerequisites


# --- run_gcloud ---


@mock.patch("subprocess.run")
def test_run_gcloud_success(mock_run: mock.Mock) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=["gcloud", "version"],
        returncode=0,
        stdout="Google Cloud SDK 400.0.0",
        stderr="",
    )
    result = run_gcloud("version")
    assert result.stdout == "Google Cloud SDK 400.0.0"
    mock_run.assert_called_once_with(
        ["gcloud", "version"],
        capture_output=True,
        text=True,
        check=True,
    )


@mock.patch("subprocess.run")
def test_run_gcloud_called_process_error(mock_run: mock.Mock) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["gcloud", "fail"], stderr="some error"
    )
    with pytest.raises(SandboxOperationError) as exc_info:
        run_gcloud("fail")
    assert exc_info.value.returncode == 1
    assert "some error" in exc_info.value.stderr


@mock.patch("subprocess.run")
def test_run_gcloud_file_not_found(mock_run: mock.Mock) -> None:
    mock_run.side_effect = FileNotFoundError()
    with pytest.raises(GCloudNotFoundError):
        run_gcloud("version")


@mock.patch("subprocess.run")
def test_run_gcloud_check_false(mock_run: mock.Mock) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=["gcloud", "config", "get-value", "account"],
        returncode=1,
        stdout="",
        stderr="",
    )
    result = run_gcloud("config", "get-value", "account", check=False)
    assert result.returncode == 1
    mock_run.assert_called_once_with(
        ["gcloud", "config", "get-value", "account"],
        capture_output=True,
        text=True,
        check=False,
    )


# --- check_gcloud_installed ---


@mock.patch("devservices.utils.sandbox.shutil.which")
def test_check_gcloud_installed_found(mock_which: mock.Mock) -> None:
    mock_which.return_value = "/usr/bin/gcloud"
    assert check_gcloud_installed() is True
    mock_which.assert_called_once_with("gcloud")


@mock.patch("devservices.utils.sandbox.shutil.which")
def test_check_gcloud_installed_not_found(mock_which: mock.Mock) -> None:
    mock_which.return_value = None
    assert check_gcloud_installed() is False
    mock_which.assert_called_once_with("gcloud")


# --- get_gcloud_account ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_account_authenticated(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="user@example.com\n", stderr=""
    )
    assert get_gcloud_account() == "user@example.com"
    mock_run_gcloud.assert_called_once_with(
        "config", "get-value", "account", check=False
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_account_not_authenticated(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="(unset)\n", stderr=""
    )
    assert get_gcloud_account() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_account_empty(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    assert get_gcloud_account() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_account_gcloud_missing(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = GCloudNotFoundError()
    assert get_gcloud_account() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_account_operation_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud config get-value account", returncode=1, stderr="error"
    )
    assert get_gcloud_account() is None


# --- get_gcloud_project ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_project_configured(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="my-project\n", stderr=""
    )
    assert get_gcloud_project() == "my-project"
    mock_run_gcloud.assert_called_once_with(
        "config", "get-value", "project", check=False
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_project_not_configured(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    assert get_gcloud_project() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_project_unset(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="(unset)\n", stderr=""
    )
    assert get_gcloud_project() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_project_gcloud_missing(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = GCloudNotFoundError()
    assert get_gcloud_project() is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_gcloud_project_operation_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud config get-value project", returncode=1, stderr="error"
    )
    assert get_gcloud_project() is None


# --- validate_sandbox_prerequisites ---


@mock.patch("devservices.utils.sandbox.get_gcloud_account")
@mock.patch("devservices.utils.sandbox.check_gcloud_installed")
def test_validate_sandbox_prerequisites_all_pass(
    mock_installed: mock.Mock,
    mock_account: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_installed.return_value = True
    mock_account.return_value = "user@example.com"
    from devservices.utils.console import Console

    console = Console()
    validate_sandbox_prerequisites(console)
    output = capsys.readouterr().out
    assert "Authenticated as user@example.com" in output


@mock.patch("devservices.utils.sandbox.check_gcloud_installed")
def test_validate_sandbox_prerequisites_gcloud_missing(
    mock_installed: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_installed.return_value = False
    from devservices.utils.console import Console

    console = Console()
    with pytest.raises(SystemExit):
        validate_sandbox_prerequisites(console)
    output = capsys.readouterr().out
    assert "gcloud CLI is not installed" in output


@mock.patch("devservices.utils.sandbox.get_gcloud_account")
@mock.patch("devservices.utils.sandbox.check_gcloud_installed")
def test_validate_sandbox_prerequisites_not_authenticated(
    mock_installed: mock.Mock,
    mock_account: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_installed.return_value = True
    mock_account.return_value = None
    from devservices.utils.console import Console

    console = Console()
    with pytest.raises(SystemExit):
        validate_sandbox_prerequisites(console)
    output = capsys.readouterr().out
    assert "gcloud is not authenticated" in output


# --- resolve_project ---


def test_resolve_project_from_arg() -> None:
    assert resolve_project("my-project") == "my-project"


@mock.patch.dict("os.environ", {"DEVSERVICES_SANDBOX_PROJECT": "env-project"})
def test_resolve_project_from_env() -> None:
    assert resolve_project(None) == "env-project"


@mock.patch.dict("os.environ", {}, clear=True)
@mock.patch("devservices.utils.sandbox.get_gcloud_project")
def test_resolve_project_from_gcloud(mock_get_project: mock.Mock) -> None:
    mock_get_project.return_value = "gcloud-project"
    assert resolve_project(None) == "gcloud-project"


@mock.patch.dict("os.environ", {}, clear=True)
@mock.patch("devservices.utils.sandbox.get_gcloud_project")
def test_resolve_project_none_found(mock_get_project: mock.Mock) -> None:
    mock_get_project.return_value = None
    with pytest.raises(SandboxOperationError) as exc_info:
        resolve_project(None)
    assert "No GCP project specified" in exc_info.value.stderr


# --- generate_instance_name ---


def test_generate_instance_name_with_name() -> None:
    assert generate_instance_name("mybox") == "sandbox-mybox"


def test_generate_instance_name_with_prefixed_name() -> None:
    assert generate_instance_name("sandbox-mybox") == "sandbox-mybox"


@mock.patch("devservices.utils.sandbox.time.time", return_value=1000000.0)
@mock.patch("devservices.utils.sandbox.getpass.getuser", return_value="testuser")
def test_generate_instance_name_auto(
    mock_getuser: mock.Mock, mock_time: mock.Mock
) -> None:
    name = generate_instance_name(None)
    assert name.startswith("sandbox-testuser-")
    assert len(name) == len("sandbox-testuser-") + 6


# --- create_instance ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_create_instance(mock_run_gcloud: mock.Mock) -> None:
    create_instance(
        name="sandbox-test",
        project="my-project",
        zone=SANDBOX_DEFAULT_ZONE,
        machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
        branch="main",
        mode="default",
        spot=False,
    )
    mock_run_gcloud.assert_called_once()
    args = mock_run_gcloud.call_args[0]
    assert "compute" in args
    assert "instances" in args
    assert "create" in args
    assert "sandbox-test" in args
    assert "--project=my-project" in args
    assert f"--zone={SANDBOX_DEFAULT_ZONE}" in args
    assert f"--machine-type={SANDBOX_DEFAULT_MACHINE_TYPE}" in args
    assert f"--image-family={SANDBOX_IMAGE_FAMILY}" in args
    assert f"--image-project={SANDBOX_IMAGE_PROJECT}" in args
    assert f"--boot-disk-size={SANDBOX_DISK_SIZE}GB" in args
    assert f"--boot-disk-type={SANDBOX_DISK_TYPE}" in args
    assert "--metadata=SANDBOX_BRANCH=main,SANDBOX_MODE=default" in args
    assert f"--tags={SANDBOX_NETWORK_TAG}" in args
    assert f"--labels={SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}" in args
    assert "--no-address" in args
    assert "--shielded-secure-boot" in args
    assert "--provisioning-model=SPOT" not in args


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_create_instance_spot(mock_run_gcloud: mock.Mock) -> None:
    create_instance(
        name="sandbox-test",
        project="my-project",
        zone=SANDBOX_DEFAULT_ZONE,
        machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
        branch="main",
        mode="default",
        spot=True,
    )
    mock_run_gcloud.assert_called_once()
    args = mock_run_gcloud.call_args[0]
    assert "--provisioning-model=SPOT" in args
    assert "--instance-termination-action=STOP" in args


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_create_instance_with_sentry_ref(mock_run_gcloud: mock.Mock) -> None:
    create_instance(
        name="sandbox-test",
        project="my-project",
        zone=SANDBOX_DEFAULT_ZONE,
        machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
        branch="main",
        mode="default",
        spot=False,
        sentry_ref="feat/my-sentry-branch",
    )
    mock_run_gcloud.assert_called_once()
    args = mock_run_gcloud.call_args[0]
    assert "--metadata=SANDBOX_BRANCH=main,SANDBOX_MODE=default,SANDBOX_SENTRY_REF=feat/my-sentry-branch" in args


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_create_instance_without_sentry_ref(mock_run_gcloud: mock.Mock) -> None:
    create_instance(
        name="sandbox-test",
        project="my-project",
        zone=SANDBOX_DEFAULT_ZONE,
        machine_type=SANDBOX_DEFAULT_MACHINE_TYPE,
        branch="main",
        mode="default",
        spot=False,
        sentry_ref=None,
    )
    mock_run_gcloud.assert_called_once()
    args = mock_run_gcloud.call_args[0]
    assert "--metadata=SANDBOX_BRANCH=main,SANDBOX_MODE=default" in args
    # Ensure SENTRY_REF is NOT in metadata when not provided
    metadata_arg = [a for a in args if a.startswith("--metadata=")][0]
    assert "SANDBOX_SENTRY_REF" not in metadata_arg


# --- start_instance ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_start_instance(mock_run_gcloud: mock.Mock) -> None:
    start_instance(name="sandbox-test", project="my-project", zone="us-central1-a")
    mock_run_gcloud.assert_called_once_with(
        "compute",
        "instances",
        "start",
        "sandbox-test",
        "--project=my-project",
        "--zone=us-central1-a",
    )


# --- stop_instance ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_stop_instance(mock_run_gcloud: mock.Mock) -> None:
    stop_instance(name="sandbox-test", project="my-project", zone="us-central1-a")
    mock_run_gcloud.assert_called_once_with(
        "compute",
        "instances",
        "stop",
        "sandbox-test",
        "--project=my-project",
        "--zone=us-central1-a",
    )


# --- delete_instance ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_delete_instance(mock_run_gcloud: mock.Mock) -> None:
    delete_instance(name="sandbox-test", project="my-project", zone="us-central1-a")
    mock_run_gcloud.assert_called_once_with(
        "compute",
        "instances",
        "delete",
        "sandbox-test",
        "--project=my-project",
        "--zone=us-central1-a",
        "--quiet",
    )


# --- get_instance_status ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_status_running(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="RUNNING\n", stderr=""
    )
    assert (
        get_instance_status("sandbox-test", "my-project", "us-central1-a") == "RUNNING"
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_status_stopped(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="TERMINATED\n", stderr=""
    )
    assert (
        get_instance_status("sandbox-test", "my-project", "us-central1-a")
        == "TERMINATED"
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_status_not_found(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud compute instances describe sandbox-test",
        returncode=1,
        stderr="not found",
    )
    assert get_instance_status("sandbox-test", "my-project", "us-central1-a") is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_status_empty(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    assert get_instance_status("sandbox-test", "my-project", "us-central1-a") is None


# --- list_instances ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_list_instances_with_instances(mock_run_gcloud: mock.Mock) -> None:
    instances_json = json.dumps(
        [
            {
                "name": "sandbox-user-abc123",
                "status": "RUNNING",
                "zone": "https://www.googleapis.com/compute/v1/projects/my-project/zones/us-central1-a",
                "machineType": "https://www.googleapis.com/compute/v1/projects/my-project/zones/us-central1-a/machineTypes/e2-standard-8",
                "metadata": {
                    "items": [
                        {"key": "SANDBOX_BRANCH", "value": "main"},
                        {"key": "SANDBOX_MODE", "value": "default"},
                    ]
                },
                "creationTimestamp": "2025-01-01T00:00:00.000-07:00",
            }
        ]
    )
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=instances_json, stderr=""
    )
    result = list_instances("my-project")
    assert len(result) == 1
    assert result[0]["name"] == "sandbox-user-abc123"
    assert result[0]["status"] == "RUNNING"
    assert result[0]["zone"] == "us-central1-a"
    assert result[0]["machine_type"] == "e2-standard-8"
    assert result[0]["branch"] == "main"
    assert result[0]["created"] == "2025-01-01T00:00:00.000-07:00"


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_list_instances_with_zone(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="[]", stderr=""
    )
    list_instances("my-project", zone="us-central1-a")
    args = mock_run_gcloud.call_args[0]
    assert "--zones=us-central1-a" in args


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_list_instances_empty(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = list_instances("my-project")
    assert result == []


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_list_instances_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud compute instances list",
        returncode=1,
        stderr="permission denied",
    )
    result = list_instances("my-project")
    assert result == []


# --- ssh_exec ---


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec(mock_execvp: mock.Mock) -> None:
    ssh_exec(name="sandbox-test", project="my-project", zone="us-central1-a")
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
        ],
    )


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec_with_ports(mock_execvp: mock.Mock) -> None:
    ssh_exec(
        name="sandbox-test",
        project="my-project",
        zone="us-central1-a",
        ports=[(8000, 8000)],
    )
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
            "--ssh-flag=-L 8000:localhost:8000",
        ],
    )


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec_with_multiple_ports(mock_execvp: mock.Mock) -> None:
    ssh_exec(
        name="sandbox-test",
        project="my-project",
        zone="us-central1-a",
        ports=[(8000, 8000), (8010, 8010), (7999, 7999)],
    )
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
            "--ssh-flag=-L 8000:localhost:8000",
            "--ssh-flag=-L 8010:localhost:8010",
            "--ssh-flag=-L 7999:localhost:7999",
        ],
    )


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec_with_no_ports(mock_execvp: mock.Mock) -> None:
    ssh_exec(
        name="sandbox-test", project="my-project", zone="us-central1-a", ports=None
    )
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
        ],
    )


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec_with_empty_ports(mock_execvp: mock.Mock) -> None:
    ssh_exec(name="sandbox-test", project="my-project", zone="us-central1-a", ports=[])
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
        ],
    )


@mock.patch("devservices.utils.sandbox.os.execvp")
def test_ssh_exec_with_custom_port_mapping(mock_execvp: mock.Mock) -> None:
    ssh_exec(
        name="sandbox-test",
        project="my-project",
        zone="us-central1-a",
        ports=[(8000, 8000), (15432, 5432)],
    )
    mock_execvp.assert_called_once_with(
        "gcloud",
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--ssh-flag=-A",
            "--ssh-flag=-L 8000:localhost:8000",
            "--ssh-flag=-L 15432:localhost:5432",
        ],
    )


# --- ssh_command ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_ssh_command_success(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="hello\n", stderr=""
    )
    result = ssh_command("sandbox-test", "my-project", "us-central1-a", "echo hello")
    assert result.stdout == "hello\n"
    mock_run_gcloud.assert_called_once_with(
        "compute",
        "ssh",
        "sandbox-test",
        "--project=my-project",
        "--zone=us-central1-a",
        "--tunnel-through-iap",
        "--command=echo hello",
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_ssh_command_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud compute ssh sandbox-test",
        returncode=1,
        stderr="connection refused",
    )
    with pytest.raises(SandboxOperationError):
        ssh_command("sandbox-test", "my-project", "us-central1-a", "echo hello")


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_ssh_command_gcloud_not_found(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = GCloudNotFoundError()
    with pytest.raises(GCloudNotFoundError):
        ssh_command("sandbox-test", "my-project", "us-central1-a", "echo hello")


# --- check_api_enabled ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_check_api_enabled_true(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="iap.googleapis.com\n", stderr=""
    )
    assert check_api_enabled("my-project", "iap.googleapis.com") is True
    mock_run_gcloud.assert_called_once_with(
        "services",
        "list",
        "--enabled",
        "--filter=name:iap.googleapis.com",
        "--format=value(name)",
        "--project=my-project",
        check=False,
    )


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_check_api_enabled_false(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    assert check_api_enabled("my-project", "iap.googleapis.com") is False


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_check_api_enabled_gcloud_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = GCloudNotFoundError()
    assert check_api_enabled("my-project", "iap.googleapis.com") is False


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_check_api_enabled_operation_error(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud services list", returncode=1, stderr="error"
    )
    assert check_api_enabled("my-project", "iap.googleapis.com") is False


# --- validate_sandbox_apis ---


@mock.patch("devservices.utils.sandbox.check_api_enabled")
def test_validate_sandbox_apis_all_enabled(
    mock_check: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_check.return_value = True
    from devservices.utils.console import Console

    console = Console()
    assert validate_sandbox_apis("my-project", console) is True
    assert mock_check.call_count == 2


@mock.patch("devservices.utils.sandbox.check_api_enabled")
def test_validate_sandbox_apis_one_missing(
    mock_check: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_check.side_effect = [True, False]
    from devservices.utils.console import Console

    console = Console()
    assert validate_sandbox_apis("my-project", console) is False
    output = capsys.readouterr().out
    assert SANDBOX_REQUIRED_APIS[1] in output


@mock.patch("devservices.utils.sandbox.check_api_enabled")
def test_validate_sandbox_apis_all_missing(
    mock_check: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_check.return_value = False
    from devservices.utils.console import Console

    console = Console()
    assert validate_sandbox_apis("my-project", console) is False
    output = capsys.readouterr().out
    for api in SANDBOX_REQUIRED_APIS:
        assert api in output


# --- get_instance_details ---


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_details_success(mock_run_gcloud: mock.Mock) -> None:
    instance_json = json.dumps(
        {
            "name": "sandbox-test",
            "status": "RUNNING",
            "zone": "https://www.googleapis.com/compute/v1/projects/my-project/zones/us-central1-a",
            "machineType": "https://www.googleapis.com/compute/v1/projects/my-project/zones/us-central1-a/machineTypes/e2-standard-8",
            "networkInterfaces": [{"networkIP": "10.0.0.2"}],
            "metadata": {
                "items": [
                    {"key": "SANDBOX_BRANCH", "value": "main"},
                    {"key": "SANDBOX_MODE", "value": "default"},
                ]
            },
            "creationTimestamp": "2025-01-01T00:00:00.000-07:00",
        }
    )
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=instance_json, stderr=""
    )
    result = get_instance_details("sandbox-test", "my-project", "us-central1-a")
    assert result is not None
    assert result["name"] == "sandbox-test"
    assert result["status"] == "RUNNING"
    assert result["zone"] == "us-central1-a"
    assert result["machine_type"] == "e2-standard-8"
    assert result["internal_ip"] == "10.0.0.2"
    assert result["branch"] == "main"
    assert result["mode"] == "default"
    assert result["created"] == "2025-01-01T00:00:00.000-07:00"


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_details_not_found(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.side_effect = SandboxOperationError(
        command="gcloud compute instances describe sandbox-test",
        returncode=1,
        stderr="not found",
    )
    result = get_instance_details("sandbox-test", "my-project", "us-central1-a")
    assert result is None


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_details_partial_data(mock_run_gcloud: mock.Mock) -> None:
    instance_json = json.dumps(
        {
            "name": "sandbox-test",
            "status": "TERMINATED",
            "metadata": {},
        }
    )
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=instance_json, stderr=""
    )
    result = get_instance_details("sandbox-test", "my-project", "us-central1-a")
    assert result is not None
    assert result["name"] == "sandbox-test"
    assert result["status"] == "TERMINATED"
    assert result["zone"] == ""
    assert result["machine_type"] == ""
    assert result["internal_ip"] == "N/A"
    assert result["branch"] == ""
    assert result["mode"] == ""
    assert result["created"] == ""


@mock.patch("devservices.utils.sandbox.run_gcloud")
def test_get_instance_details_empty_stdout(mock_run_gcloud: mock.Mock) -> None:
    mock_run_gcloud.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = get_instance_details("sandbox-test", "my-project", "us-central1-a")
    assert result is None


# --- start_port_forward ---


@mock.patch("subprocess.Popen")
def test_start_port_forward_success(mock_popen: mock.Mock) -> None:
    mock_proc = mock.Mock()
    mock_popen.return_value = mock_proc
    result = start_port_forward("sandbox-test", "my-project", "us-central1-a", [(8000, 8000)])
    assert result is mock_proc
    mock_popen.assert_called_once_with(
        [
            "gcloud",
            "compute",
            "ssh",
            "sandbox-test",
            "--project=my-project",
            "--zone=us-central1-a",
            "--tunnel-through-iap",
            "--",
            "-N",
            "-L",
            "8000:localhost:8000",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@mock.patch("subprocess.Popen")
def test_start_port_forward_multiple_ports(mock_popen: mock.Mock) -> None:
    mock_proc = mock.Mock()
    mock_popen.return_value = mock_proc
    result = start_port_forward(
        "sandbox-test", "my-project", "us-central1-a", [(8000, 8000), (9000, 9000)]
    )
    assert result is mock_proc
    call_args = mock_popen.call_args[0][0]
    assert "-L" in call_args
    assert "8000:localhost:8000" in call_args
    assert "9000:localhost:9000" in call_args


@mock.patch("subprocess.Popen")
def test_start_port_forward_custom_mapping(mock_popen: mock.Mock) -> None:
    mock_proc = mock.Mock()
    mock_popen.return_value = mock_proc
    result = start_port_forward(
        "sandbox-test", "my-project", "us-central1-a", [(8000, 8000), (15432, 5432)]
    )
    assert result is mock_proc
    call_args = mock_popen.call_args[0][0]
    assert "8000:localhost:8000" in call_args
    assert "15432:localhost:5432" in call_args


@mock.patch("subprocess.Popen")
def test_start_port_forward_gcloud_not_found(mock_popen: mock.Mock) -> None:
    mock_popen.side_effect = FileNotFoundError()
    with pytest.raises(GCloudNotFoundError):
        start_port_forward("sandbox-test", "my-project", "us-central1-a", [(8000, 8000)])


# --- stop_port_forward ---


@mock.patch("devservices.utils.sandbox.os.kill")
def test_stop_port_forward_success(mock_kill: mock.Mock) -> None:
    stop_port_forward(12345)
    mock_kill.assert_called_once()
    args = mock_kill.call_args[0]
    assert args[0] == 12345


@mock.patch("devservices.utils.sandbox.os.kill")
def test_stop_port_forward_process_already_dead(mock_kill: mock.Mock) -> None:
    mock_kill.side_effect = ProcessLookupError()
    stop_port_forward(12345)
    mock_kill.assert_called_once()


# --- is_port_forward_running ---


@mock.patch("devservices.utils.sandbox.os.kill")
def test_is_port_forward_running_true(mock_kill: mock.Mock) -> None:
    mock_kill.return_value = None
    assert is_port_forward_running(12345) is True
    mock_kill.assert_called_once_with(12345, 0)


@mock.patch("devservices.utils.sandbox.os.kill")
def test_is_port_forward_running_false(mock_kill: mock.Mock) -> None:
    mock_kill.side_effect = ProcessLookupError()
    assert is_port_forward_running(12345) is False


@mock.patch("devservices.utils.sandbox.os.kill")
def test_is_port_forward_running_permission_error(mock_kill: mock.Mock) -> None:
    mock_kill.side_effect = PermissionError()
    assert is_port_forward_running(12345) is False
