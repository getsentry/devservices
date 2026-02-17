from __future__ import annotations

import time
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import SANDBOX_DEFAULT_MACHINE_TYPE
from devservices.constants import SANDBOX_DEFAULT_PORTS
from devservices.constants import SANDBOX_DEFAULT_ZONE
from devservices.constants import SANDBOX_MAINTENANCE_SYNC_PATH
from devservices.exceptions import SandboxAlreadyExistsError
from devservices.exceptions import SandboxError
from devservices.exceptions import SandboxNotFoundError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.sandbox import create_instance
from devservices.utils.sandbox import delete_instance
from devservices.utils.sandbox import generate_instance_name
from devservices.utils.sandbox import get_instance_details
from devservices.utils.sandbox import get_instance_status
from devservices.utils.sandbox import is_port_forward_running
from devservices.utils.sandbox import list_instances
from devservices.utils.sandbox import resolve_project
from devservices.utils.sandbox import ssh_command
from devservices.utils.sandbox import ssh_exec
from devservices.utils.sandbox import start_instance
from devservices.utils.sandbox import start_port_forward
from devservices.utils.sandbox import stop_instance
from devservices.utils.sandbox import stop_port_forward
from devservices.utils.sandbox import validate_sandbox_apis
from devservices.utils.sandbox import validate_sandbox_prerequisites
from devservices.utils.state import State


SANDBOX_STATUS_POLL_INTERVAL = 5
SANDBOX_STATUS_POLL_TIMEOUT = 120


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    sandbox_parser = subparsers.add_parser(
        "sandbox", help="Manage GCE sandbox development environments"
    )
    sandbox_subparsers = sandbox_parser.add_subparsers(
        dest="sandbox_command", title="sandbox commands", metavar=""
    )

    # create
    create_parser = sandbox_subparsers.add_parser(
        "create", help="Create a new sandbox environment"
    )
    create_parser.add_argument(
        "name", nargs="?", default=None, help="Name for the sandbox instance"
    )
    create_parser.add_argument(
        "--branch", default="master", help="Git branch to use (default: master)"
    )
    create_parser.add_argument(
        "--mode", default="default", help="Devservices mode (default: default)"
    )
    create_parser.add_argument(
        "--machine-type",
        default=SANDBOX_DEFAULT_MACHINE_TYPE,
        help=f"GCE machine type (default: {SANDBOX_DEFAULT_MACHINE_TYPE})",
    )
    create_parser.add_argument("--project", default=None, help="GCP project ID")
    create_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    create_parser.add_argument(
        "--spot",
        action="store_true",
        default=False,
        help="Use spot/preemptible VM (cheaper but may be reclaimed)",
    )
    create_parser.set_defaults(func=sandbox_create)

    # ssh
    ssh_parser = sandbox_subparsers.add_parser(
        "ssh", help="SSH into a sandbox environment"
    )
    ssh_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    ssh_parser.add_argument("--project", default=None, help="GCP project ID")
    ssh_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    ssh_parser.add_argument(
        "--ports",
        default=None,
        help="Comma-separated ports to forward (default: 8000)",
    )
    ssh_parser.add_argument(
        "--no-forward",
        action="store_true",
        default=False,
        help="Skip automatic port forwarding",
    )
    ssh_parser.set_defaults(func=sandbox_ssh)

    # stop
    stop_parser = sandbox_subparsers.add_parser(
        "stop", help="Stop a sandbox (preserves disk)"
    )
    stop_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    stop_parser.add_argument("--project", default=None, help="GCP project ID")
    stop_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    stop_parser.set_defaults(func=sandbox_stop)

    # start
    start_parser = sandbox_subparsers.add_parser(
        "start", help="Start a stopped sandbox"
    )
    start_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    start_parser.add_argument("--project", default=None, help="GCP project ID")
    start_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    start_parser.set_defaults(func=sandbox_start)

    # destroy
    destroy_parser = sandbox_subparsers.add_parser(
        "destroy", help="Destroy a sandbox (deletes VM and disk)"
    )
    destroy_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    destroy_parser.add_argument("--project", default=None, help="GCP project ID")
    destroy_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    destroy_parser.set_defaults(func=sandbox_destroy)

    # list
    list_parser = sandbox_subparsers.add_parser(
        "list", help="List all sandbox environments"
    )
    list_parser.add_argument("--project", default=None, help="GCP project ID")
    list_parser.add_argument(
        "--zone", default=None, help="GCE zone (default: all zones)"
    )
    list_parser.set_defaults(func=sandbox_list)

    # sync
    sync_parser = sandbox_subparsers.add_parser(
        "sync", help="Sync sandbox with latest branch changes"
    )
    sync_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    sync_parser.add_argument("--project", default=None, help="GCP project ID")
    sync_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    sync_parser.set_defaults(func=sandbox_sync)

    # status
    status_parser = sandbox_subparsers.add_parser(
        "status", help="Show detailed sandbox status"
    )
    status_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    status_parser.add_argument("--project", default=None, help="GCP project ID")
    status_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    status_parser.set_defaults(func=sandbox_status)

    # port-forward
    pf_parser = sandbox_subparsers.add_parser(
        "port-forward", help="Forward ports from sandbox to localhost"
    )
    pf_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    pf_parser.add_argument(
        "--ports", default=None, help="Comma-separated ports to forward (default: 8000)"
    )
    pf_parser.add_argument(
        "--stop", action="store_true", default=False, help="Stop port forwarding"
    )
    pf_parser.add_argument("--project", default=None, help="GCP project ID")
    pf_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    pf_parser.set_defaults(func=sandbox_port_forward)

    # Default: show help when no subcommand given
    sandbox_parser.set_defaults(
        func=lambda args: sandbox_parser.print_help(),
        command="sandbox",
    )


def _resolve_sandbox_name(args: Namespace, state: State, console: Console) -> str:
    """Resolve sandbox name from args or default to most recent."""
    name: str | None = getattr(args, "name", None)
    if name:
        if not name.startswith("sandbox-"):
            name = f"sandbox-{name}"
        return name
    default = state.get_default_sandbox()
    if default:
        return default
    console.failure("No sandbox name provided and no existing sandboxes found.")
    console.info("Create one with: devservices sandbox create [NAME]")
    exit(1)


def _wait_for_status(
    name: str, project: str, zone: str, target_status: str, status: Status
) -> bool:
    """Poll instance status until it matches target or timeout."""
    elapsed = 0
    while elapsed < SANDBOX_STATUS_POLL_TIMEOUT:
        current = get_instance_status(name, project, zone)
        if current == target_status:
            return True
        status.info(
            f"Waiting for '{name}' to be {target_status} (currently {current})..."
        )
        time.sleep(SANDBOX_STATUS_POLL_INTERVAL)
        elapsed += SANDBOX_STATUS_POLL_INTERVAL
    return False


def _stop_port_forward(name: str, state: State, console: Console) -> None:
    """Stop port forwarding for a sandbox if active."""
    pid = state.get_port_forward_pid(name)
    if not pid:
        return
    if is_port_forward_running(pid):
        stop_port_forward(pid)
        console.info(f"Port forwarding stopped (PID {pid})")
    state.update_port_forward_pid(name, None)


def sandbox_create(args: Namespace) -> None:
    """Create a new sandbox environment."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    if not validate_sandbox_apis(project, console):
        exit(1)

    name = generate_instance_name(args.name)
    zone = args.zone
    machine_type = args.machine_type
    branch = args.branch
    mode = args.mode
    spot = args.spot

    # Check if instance already exists
    existing_status = get_instance_status(name, project, zone)
    if existing_status is not None:
        console.failure(str(SandboxAlreadyExistsError(name)))
        exit(1)

    state = State()
    with Status(
        lambda: console.warning(
            f"Creating sandbox '{name}' (branch: {branch}, type: {machine_type})"
        ),
        lambda: console.success(f"Sandbox '{name}' created successfully"),
    ) as status_ctx:
        try:
            create_instance(
                name=name,
                project=project,
                zone=zone,
                machine_type=machine_type,
                branch=branch,
                mode=mode,
                spot=spot,
            )
        except SandboxError as e:
            capture_exception(e, level="info")
            status_ctx.failure(f"Failed to create sandbox: {e}")
            exit(1)

        state.add_sandbox_instance(name, project, zone, machine_type, branch, mode)

        if not _wait_for_status(name, project, zone, "RUNNING", status_ctx):
            status_ctx.warning(
                f"Sandbox '{name}' created but not yet running. Check status with: devservices sandbox list"
            )
        else:
            state.update_sandbox_status(name, "RUNNING")

    console.info(f"\nTo connect: devservices sandbox ssh {name}")


def sandbox_ssh(args: Namespace) -> None:
    """SSH into a sandbox environment."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    status = get_instance_status(name, project, zone)
    if status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)
    if status != "RUNNING":
        console.failure(
            f"Sandbox '{name}' is {status}. Start it first with: devservices sandbox start {name}"
        )
        exit(1)

    # Resolve ports for forwarding
    if args.no_forward:
        ports = None
    elif args.ports:
        ports = [int(p.strip()) for p in args.ports.split(",")]
    else:
        ports = SANDBOX_DEFAULT_PORTS

    console.info(f"Connecting to sandbox '{name}'...")
    if ports:
        port_str = ", ".join(str(p) for p in ports)
        console.info(f"Forwarding ports: {port_str}")
    ssh_exec(name, project, zone, ports=ports)


def sandbox_stop(args: Namespace) -> None:
    """Stop a sandbox environment (preserves disk)."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    current_status = get_instance_status(name, project, zone)
    if current_status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)
    if current_status in ("TERMINATED", "STOPPED"):
        console.warning(f"Sandbox '{name}' is already stopped.")
        return

    _stop_port_forward(name, state, console)

    with Status(
        lambda: console.warning(f"Stopping sandbox '{name}'..."),
        lambda: console.success(f"Sandbox '{name}' stopped. Disk preserved."),
    ) as status_ctx:
        try:
            stop_instance(name, project, zone)
        except SandboxError as e:
            capture_exception(e, level="info")
            status_ctx.failure(f"Failed to stop sandbox: {e}")
            exit(1)
        state.update_sandbox_status(name, "TERMINATED")

    console.info(f"Resume with: devservices sandbox start {name}")


def sandbox_start(args: Namespace) -> None:
    """Start a stopped sandbox environment."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    current_status = get_instance_status(name, project, zone)
    if current_status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)
    if current_status == "RUNNING":
        console.warning(f"Sandbox '{name}' is already running.")
        console.info(f"Connect with: devservices sandbox ssh {name}")
        return

    with Status(
        lambda: console.warning(f"Starting sandbox '{name}'..."),
        lambda: console.success(f"Sandbox '{name}' started"),
    ) as status_ctx:
        try:
            start_instance(name, project, zone)
        except SandboxError as e:
            capture_exception(e, level="info")
            status_ctx.failure(f"Failed to start sandbox: {e}")
            exit(1)

        if not _wait_for_status(name, project, zone, "RUNNING", status_ctx):
            status_ctx.warning(
                f"Sandbox '{name}' may still be starting. Check status with: devservices sandbox list"
            )
        else:
            state.update_sandbox_status(name, "RUNNING")

    console.info(f"Connect with: devservices sandbox ssh {name}")


def sandbox_destroy(args: Namespace) -> None:
    """Destroy a sandbox environment (deletes VM and disk)."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    current_status = get_instance_status(name, project, zone)
    if current_status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)

    _stop_port_forward(name, state, console)

    if not console.confirm(
        f"Are you sure you want to destroy sandbox '{name}'? This will delete the VM and all its data."
    ):
        console.info("Destroy cancelled.")
        return

    with Status(
        lambda: console.warning(f"Destroying sandbox '{name}'..."),
        lambda: console.success(f"Sandbox '{name}' destroyed"),
    ):
        try:
            delete_instance(name, project, zone)
        except SandboxError as e:
            capture_exception(e, level="info")
            console.failure(f"Failed to destroy sandbox: {e}")
            exit(1)
        state.remove_sandbox_instance(name)


def sandbox_list(args: Namespace) -> None:
    """List all sandbox environments."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    zone = getattr(args, "zone", None)

    with Status(
        lambda: console.info("Fetching sandbox instances..."),
    ):
        instances = list_instances(project, zone)

    if not instances:
        console.info("No sandbox instances found.")
        console.info("Create one with: devservices sandbox create [NAME]")
        return

    # Format table header
    header = f"{'NAME':<30} {'STATUS':<12} {'ZONE':<20} {'MACHINE TYPE':<18} {'BRANCH':<15} {'CREATED':<25}"
    console.info(header, bold=True)
    console.info("-" * len(header))

    for inst in instances:
        line = f"{inst['name']:<30} {inst['status']:<12} {inst['zone']:<20} {inst['machine_type']:<18} {inst['branch']:<15} {inst['created']:<25}"
        console.info(line)


def sandbox_sync(args: Namespace) -> None:
    """Sync sandbox with latest branch changes."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    status = get_instance_status(name, project, zone)
    if status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)
    if status != "RUNNING":
        console.failure(
            f"Sandbox '{name}' is {status}. Start it first with: devservices sandbox start {name}"
        )
        exit(1)

    instance = state.get_sandbox_instance(name)
    branch = instance["branch"] if instance else "master"

    console.info(f"Syncing sandbox '{name}' to latest '{branch}'...")

    try:
        result = ssh_command(
            name, project, zone, f"{SANDBOX_MAINTENANCE_SYNC_PATH} {branch}"
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                console.info(f"  {line}")
        console.success(f"Sandbox '{name}' synced successfully")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to sync sandbox: {e}")
        exit(1)


def sandbox_status(args: Namespace) -> None:
    """Show detailed sandbox status."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    with Status(
        lambda: console.info(f"Fetching status for '{name}'..."),
    ):
        details = get_instance_details(name, project, zone)

    if details is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)

    console.info(f"Sandbox: {details['name']}", bold=True)
    console.info(f"  Status:       {details['status']}")
    console.info(f"  Zone:         {details['zone']}")
    console.info(f"  Machine Type: {details['machine_type']}")
    console.info(f"  Branch:       {details.get('branch', 'N/A')}")
    console.info(f"  Mode:         {details.get('mode', 'N/A')}")
    console.info(f"  Internal IP:  {details.get('internal_ip', 'N/A')}")
    console.info(f"  Created:      {details.get('created', 'N/A')}")

    local_instance = state.get_sandbox_instance(name)
    if local_instance:
        pid_str = local_instance.get("port_forward_pid")
        if pid_str and is_port_forward_running(int(pid_str)):
            console.info(f"  Port Forward: Active (PID {pid_str})")
        elif pid_str:
            console.info(f"  Port Forward: Stale (PID {pid_str} not running)")
            state.update_port_forward_pid(name, None)
        else:
            console.info("  Port Forward: Not active")

    if details["status"] == "RUNNING":
        console.info(f"\n  Connect: devservices sandbox ssh {name}")
        console.info(f"  Sync:    devservices sandbox sync {name}")
        console.info(f"  Forward: devservices sandbox port-forward {name}")


def sandbox_port_forward(args: Namespace) -> None:
    """Forward ports from sandbox to localhost."""
    console = Console()
    validate_sandbox_prerequisites(console)

    try:
        project = resolve_project(args.project)
    except SandboxError as e:
        console.failure(str(e))
        exit(1)

    state = State()
    name = _resolve_sandbox_name(args, state, console)
    zone = args.zone

    if args.stop:
        pid = state.get_port_forward_pid(name)
        if not pid:
            console.info(f"No active port forwarding for '{name}'.")
            return
        if is_port_forward_running(pid):
            stop_port_forward(pid)
            console.success(f"Port forwarding stopped (PID {pid})")
        else:
            console.info(f"Port forwarding process (PID {pid}) already stopped.")
        state.update_port_forward_pid(name, None)
        return

    ports = (
        [int(p.strip()) for p in args.ports.split(",")]
        if args.ports
        else SANDBOX_DEFAULT_PORTS
    )

    status = get_instance_status(name, project, zone)
    if status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)
    if status != "RUNNING":
        console.failure(
            f"Sandbox '{name}' is {status}. Start it first with: devservices sandbox start {name}"
        )
        exit(1)

    existing_pid = state.get_port_forward_pid(name)
    if existing_pid and is_port_forward_running(existing_pid):
        console.warning(f"Port forwarding already active (PID {existing_pid})")
        console.info("Use --stop to stop it first.")
        return

    console.info(f"Starting port forwarding for '{name}'...")
    try:
        proc = start_port_forward(name, project, zone, ports)
        state.update_port_forward_pid(name, proc.pid)
        port_str = ", ".join(str(p) for p in ports)
        console.success(f"Port forwarding active (PID {proc.pid})")
        console.info(f"  Forwarding ports: {port_str}")
        for port in ports:
            console.info(f"  http://localhost:{port} -> sandbox:{port}")
        console.info(f"\nStop with: devservices sandbox port-forward {name} --stop")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to start port forwarding: {e}")
        exit(1)
