from __future__ import annotations

import getpass
import hashlib
import os
import shutil
import subprocess
import time

from devservices.constants import SANDBOX_DISK_SIZE
from devservices.constants import SANDBOX_DISK_TYPE
from devservices.constants import SANDBOX_IMAGE_FAMILY
from devservices.constants import SANDBOX_IMAGE_PROJECT
from devservices.constants import SANDBOX_LABEL_KEY
from devservices.constants import SANDBOX_LABEL_VALUE
from devservices.constants import SANDBOX_NETWORK_TAG
from devservices.exceptions import GCloudAuthError
from devservices.exceptions import GCloudNotFoundError
from devservices.exceptions import SandboxOperationError
from devservices.utils.console import Console


def run_gcloud(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a gcloud CLI command and return the result."""
    cmd = ["gcloud", *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )
    except FileNotFoundError:
        raise GCloudNotFoundError()
    except subprocess.CalledProcessError as e:
        raise SandboxOperationError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stderr=e.stderr.strip(),
        )


def check_gcloud_installed() -> bool:
    """Check if gcloud CLI is installed."""
    return shutil.which("gcloud") is not None


def get_gcloud_account() -> str | None:
    """Get the currently authenticated gcloud account."""
    try:
        result = run_gcloud("config", "get-value", "account", check=False)
        account = result.stdout.strip()
        if account and account != "(unset)":
            return account
        return None
    except GCloudNotFoundError:
        return None
    except SandboxOperationError:
        return None


def get_gcloud_project() -> str | None:
    """Get the currently configured gcloud project."""
    try:
        result = run_gcloud("config", "get-value", "project", check=False)
        project = result.stdout.strip()
        if project and project != "(unset)":
            return project
        return None
    except GCloudNotFoundError:
        return None
    except SandboxOperationError:
        return None


def validate_sandbox_prerequisites(console: Console) -> None:
    """Validate all prerequisites for sandbox operations."""
    if not check_gcloud_installed():
        console.failure(str(GCloudNotFoundError()))
        exit(1)

    account = get_gcloud_account()
    if not account:
        console.failure(str(GCloudAuthError()))
        exit(1)

    console.info(f"Authenticated as {account}")


def resolve_project(project_arg: str | None) -> str:
    """Resolve the GCP project to use."""
    if project_arg:
        return project_arg
    env_project = os.environ.get("DEVSERVICES_SANDBOX_PROJECT")
    if env_project:
        return env_project
    gcloud_project = get_gcloud_project()
    if gcloud_project:
        return gcloud_project
    raise SandboxOperationError(
        command="resolve project",
        returncode=1,
        stderr="No GCP project specified. Use --project, set DEVSERVICES_SANDBOX_PROJECT, or run 'gcloud config set project PROJECT_ID'",
    )


def generate_instance_name(name: str | None) -> str:
    """Generate a sandbox instance name."""
    if name:
        if not name.startswith("sandbox-"):
            return f"sandbox-{name}"
        return name
    username = getpass.getuser()
    hash_input = f"{username}-{time.time()}"
    short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:6]
    return f"sandbox-{username}-{short_hash}"


def create_instance(
    name: str,
    project: str,
    zone: str,
    machine_type: str,
    branch: str,
    mode: str,
    spot: bool,
) -> None:
    """Create a new GCE sandbox instance."""
    args = [
        "compute",
        "instances",
        "create",
        name,
        f"--project={project}",
        f"--zone={zone}",
        f"--machine-type={machine_type}",
        f"--image-family={SANDBOX_IMAGE_FAMILY}",
        f"--image-project={SANDBOX_IMAGE_PROJECT}",
        f"--boot-disk-size={SANDBOX_DISK_SIZE}GB",
        f"--boot-disk-type={SANDBOX_DISK_TYPE}",
        f"--metadata=SANDBOX_BRANCH={branch},SANDBOX_MODE={mode}",
        f"--tags={SANDBOX_NETWORK_TAG}",
        f"--labels={SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}",
        "--no-address",
        "--shielded-secure-boot",
    ]
    if spot:
        args.append("--provisioning-model=SPOT")
        args.append("--instance-termination-action=STOP")
    run_gcloud(*args)


def start_instance(name: str, project: str, zone: str) -> None:
    """Start a stopped GCE sandbox instance."""
    run_gcloud(
        "compute",
        "instances",
        "start",
        name,
        f"--project={project}",
        f"--zone={zone}",
    )


def stop_instance(name: str, project: str, zone: str) -> None:
    """Stop a running GCE sandbox instance."""
    run_gcloud(
        "compute",
        "instances",
        "stop",
        name,
        f"--project={project}",
        f"--zone={zone}",
    )


def delete_instance(name: str, project: str, zone: str) -> None:
    """Delete a GCE sandbox instance and its disk."""
    run_gcloud(
        "compute",
        "instances",
        "delete",
        name,
        f"--project={project}",
        f"--zone={zone}",
        "--quiet",
    )


def get_instance_status(name: str, project: str, zone: str) -> str | None:
    """Get the status of a GCE sandbox instance. Returns None if not found."""
    try:
        result = run_gcloud(
            "compute",
            "instances",
            "describe",
            name,
            f"--project={project}",
            f"--zone={zone}",
            "--format=value(status)",
        )
        status = result.stdout.strip()
        return status if status else None
    except SandboxOperationError:
        return None


def list_instances(project: str, zone: str | None = None) -> list[dict[str, str]]:
    """List all sandbox instances in the project."""
    import json as json_mod

    args = [
        "compute",
        "instances",
        "list",
        f"--project={project}",
        f"--filter=labels.{SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}",
        "--format=json(name,status,zone,machineType,metadata.items,creationTimestamp)",
    ]
    if zone:
        args.append(f"--zones={zone}")

    try:
        result = run_gcloud(*args)
        instances = json_mod.loads(result.stdout) if result.stdout.strip() else []
        parsed = []
        for inst in instances:
            metadata = {}
            for item in inst.get("metadata", {}).get("items", []):
                metadata[item["key"]] = item["value"]
            parsed.append(
                {
                    "name": inst.get("name", ""),
                    "status": inst.get("status", ""),
                    "zone": inst.get("zone", "").rsplit("/", 1)[-1]
                    if inst.get("zone")
                    else "",
                    "machine_type": inst.get("machineType", "").rsplit("/", 1)[-1]
                    if inst.get("machineType")
                    else "",
                    "branch": metadata.get("SANDBOX_BRANCH", ""),
                    "created": inst.get("creationTimestamp", ""),
                }
            )
        return parsed
    except SandboxOperationError:
        return []


def ssh_exec(name: str, project: str, zone: str) -> None:
    """SSH into a sandbox instance via IAP tunnel. Replaces the current process."""
    cmd = [
        "gcloud",
        "compute",
        "ssh",
        name,
        f"--project={project}",
        f"--zone={zone}",
        "--tunnel-through-iap",
        "--ssh-flag=-A",
    ]
    os.execvp("gcloud", cmd)
