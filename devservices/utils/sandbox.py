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
    sentry_ref: str | None = None,
) -> None:
    """Create a new GCE sandbox instance."""
    metadata = f"SANDBOX_BRANCH={branch},SANDBOX_MODE={mode}"
    if sentry_ref:
        metadata += f",SANDBOX_SENTRY_REF={sentry_ref}"
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
        f"--metadata={metadata}",
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


def ssh_exec(
    name: str,
    project: str,
    zone: str,
    ports: list[tuple[int, int]] | None = None,
) -> None:
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
    if ports:
        for local_port, remote_port in ports:
            cmd.append(f"--ssh-flag=-L {local_port}:localhost:{remote_port}")
    os.execvp("gcloud", cmd)


def ssh_command(
    name: str, project: str, zone: str, command: str
) -> subprocess.CompletedProcess[str]:
    """Run a command on a sandbox instance via SSH."""
    return run_gcloud(
        "compute",
        "ssh",
        name,
        f"--project={project}",
        f"--zone={zone}",
        "--tunnel-through-iap",
        f"--command={command}",
    )


def ssh_stream(
    name: str, project: str, zone: str, command: str
) -> subprocess.Popen[bytes]:
    """Run a command on a sandbox instance via SSH with output streamed to the terminal.

    Unlike ssh_command() which captures output, this passes stdout/stderr
    directly through to the caller's terminal, suitable for follow/tail mode.
    """
    cmd = [
        "gcloud",
        "compute",
        "ssh",
        name,
        f"--project={project}",
        f"--zone={zone}",
        "--tunnel-through-iap",
        f"--command={command}",
    ]
    try:
        return subprocess.Popen(cmd)
    except FileNotFoundError:
        raise GCloudNotFoundError()


def check_api_enabled(project: str, api_name: str) -> bool:
    """Check if a GCP API is enabled on the project."""
    try:
        result = run_gcloud(
            "services",
            "list",
            "--enabled",
            f"--filter=name:{api_name}",
            "--format=value(name)",
            f"--project={project}",
            check=False,
        )
        return api_name in result.stdout.strip()
    except (GCloudNotFoundError, SandboxOperationError):
        return False


def validate_sandbox_apis(project: str, console: Console) -> bool:
    """Validate that required GCP APIs are enabled."""
    from devservices.constants import SANDBOX_REQUIRED_APIS

    all_enabled = True
    for api_name in SANDBOX_REQUIRED_APIS:
        if not check_api_enabled(project, api_name):
            console.failure(
                f"Required API '{api_name}' is not enabled on project '{project}'. "
                f"Enable it with: gcloud services enable {api_name} --project={project}"
            )
            all_enabled = False
    return all_enabled


def get_instance_details(name: str, project: str, zone: str) -> dict[str, str] | None:
    """Get detailed information about a sandbox instance."""
    import json as json_mod

    try:
        result = run_gcloud(
            "compute",
            "instances",
            "describe",
            name,
            f"--project={project}",
            f"--zone={zone}",
            "--format=json",
        )
        inst = json_mod.loads(result.stdout) if result.stdout.strip() else None
        if inst is None:
            return None

        metadata = {}
        for item in inst.get("metadata", {}).get("items", []):
            metadata[item["key"]] = item["value"]

        return {
            "name": inst.get("name", ""),
            "status": inst.get("status", ""),
            "zone": inst.get("zone", "").rsplit("/", 1)[-1] if inst.get("zone") else "",
            "machine_type": inst.get("machineType", "").rsplit("/", 1)[-1]
            if inst.get("machineType")
            else "",
            "internal_ip": inst.get("networkInterfaces", [{}])[0].get(
                "networkIP", "N/A"
            ),
            "branch": metadata.get("SANDBOX_BRANCH", ""),
            "mode": metadata.get("SANDBOX_MODE", ""),
            "created": inst.get("creationTimestamp", ""),
        }
    except SandboxOperationError:
        return None


def start_port_forward(
    name: str, project: str, zone: str, ports: list[tuple[int, int]]
) -> subprocess.Popen[bytes]:
    """Start a background SSH tunnel for port forwarding."""
    tunnel_args = []
    for local_port, remote_port in ports:
        tunnel_args.extend(["-L", f"{local_port}:localhost:{remote_port}"])

    cmd = [
        "gcloud",
        "compute",
        "ssh",
        name,
        f"--project={project}",
        f"--zone={zone}",
        "--tunnel-through-iap",
        "--",
        "-N",
        *tunnel_args,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc
    except FileNotFoundError:
        raise GCloudNotFoundError()


def stop_port_forward(pid: int) -> None:
    """Stop a port-forward process by PID."""
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def is_port_forward_running(pid: int) -> bool:
    """Check if a port-forward process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
