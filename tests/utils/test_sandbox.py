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
from devservices.exceptions import GCloudNotFoundError
from devservices.exceptions import SandboxOperationError
from devservices.utils.sandbox import check_gcloud_installed
from devservices.utils.sandbox import create_instance
from devservices.utils.sandbox import delete_instance
from devservices.utils.sandbox import generate_instance_name
from devservices.utils.sandbox import get_gcloud_account
from devservices.utils.sandbox import get_gcloud_project
from devservices.utils.sandbox import get_instance_status
from devservices.utils.sandbox import list_instances
from devservices.utils.sandbox import resolve_project
from devservices.utils.sandbox import run_gcloud
from devservices.utils.sandbox import ssh_exec
from devservices.utils.sandbox import start_instance
from devservices.utils.sandbox import stop_instance
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
