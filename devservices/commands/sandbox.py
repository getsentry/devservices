from __future__ import annotations

import time
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import SANDBOX_DEFAULT_MACHINE_TYPE
from devservices.constants import SANDBOX_DEFAULT_LOG_LINES
from devservices.constants import SANDBOX_DEFAULT_PORTS
from devservices.constants import SANDBOX_PORT_PROFILES
from devservices.constants import SANDBOX_DEFAULT_ZONE
from devservices.constants import SANDBOX_MAINTENANCE_SYNC_PATH
from devservices.exceptions import SandboxAlreadyExistsError
from devservices.exceptions import SandboxError
from devservices.exceptions import SandboxNotFoundError
from devservices.exceptions import SandboxOperationError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.sandbox import create_instance
from devservices.utils.sandbox import delete_instance
from devservices.utils.sandbox import generate_instance_name
from devservices.utils.sandbox import generate_ssh_config
from devservices.utils.sandbox import get_instance_details
from devservices.utils.sandbox import get_instance_status
from devservices.utils.sandbox import get_ssh_config_path
from devservices.utils.sandbox import is_port_forward_running
from devservices.utils.sandbox import list_instances
from devservices.utils.sandbox import remove_ssh_config_entry
from devservices.utils.sandbox import resolve_project
from devservices.utils.sandbox import ssh_command
from devservices.utils.sandbox import ssh_exec
from devservices.utils.sandbox import ssh_stream
from devservices.utils.sandbox import start_instance
from devservices.utils.sandbox import start_port_forward
from devservices.utils.sandbox import stop_instance
from devservices.utils.sandbox import stop_port_forward
from devservices.utils.sandbox import validate_sandbox_apis
from devservices.utils.sandbox import validate_sandbox_prerequisites
from devservices.utils.sandbox import write_ssh_config_entry
from devservices.utils.state import State


SANDBOX_STATUS_POLL_INTERVAL = 5
SANDBOX_STATUS_POLL_TIMEOUT = 120

SANDBOX_SYSTEMD_SERVICES = {
    "devserver": "sandbox-devserver.service",
    "startup": "sandbox-startup.service",
}


def _parse_port_specs(
    ports_arg: str | None,
) -> list[tuple[int, int]]:
    """Parse port specifications into (local_port, remote_port) tuples.

    Supports: '8000' (same local/remote), '15432:5432' (custom local port),
    comma-separated: '8000,15432:5432', or a profile name (devserver, services, all).
    """
    if not ports_arg:
        return [(p, p) for p in SANDBOX_DEFAULT_PORTS]
    if ports_arg in SANDBOX_PORT_PROFILES:
        return list(SANDBOX_PORT_PROFILES[ports_arg])
    result = []
    for spec in ports_arg.split(","):
        spec = spec.strip()
        if ":" in spec:
            local_str, remote_str = spec.split(":", 1)
            result.append((int(local_str), int(remote_str)))
        else:
            port = int(spec)
            result.append((port, port))
    return result


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
        "--branch", default="master", help="Getsentry branch (default: master)"
    )
    create_parser.add_argument(
        "--sentry-ref",
        default=None,
        help="Sentry branch or SHA (default: pinned in getsentry/sentry-version)",
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
        help="Port specs: PORT, LOCAL:REMOTE, or profile name (devserver, services, all). Comma-separated.",
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
    sync_parser.add_argument(
        "--sentry-ref",
        default=None,
        help="Sentry branch or SHA override (default: pinned in getsentry/sentry-version)",
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
        "--ports", default=None, help="Port specs: PORT, LOCAL:REMOTE, or profile name (devserver, services, all). Comma-separated."
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

    # logs
    logs_parser = sandbox_subparsers.add_parser(
        "logs", help="View logs from a sandbox service"
    )
    logs_parser.add_argument(
        "service",
        nargs="?",
        default="devserver",
        help="Service to view logs for: devserver (default), startup, or a Docker container name (e.g. postgres, redis, snuba)",
    )
    logs_parser.add_argument(
        "--name", default=None, help="Sandbox name (default: most recent)"
    )
    logs_parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        default=False,
        help="Follow log output (tail -f style)",
    )
    logs_parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=SANDBOX_DEFAULT_LOG_LINES,
        help=f"Number of recent lines to show (default: {SANDBOX_DEFAULT_LOG_LINES})",
    )
    logs_parser.add_argument("--project", default=None, help="GCP project ID")
    logs_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    logs_parser.set_defaults(func=sandbox_logs)

    # ssh-config
    ssh_config_parser = sandbox_subparsers.add_parser(
        "ssh-config",
        help="Generate SSH config for a sandbox (enables VS Code, JetBrains, Mutagen)",
    )
    ssh_config_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    ssh_config_parser.add_argument(
        "--ports",
        default=None,
        help="Port specs for LocalForward: PORT or LOCAL:REMOTE, comma-separated",
    )
    ssh_config_parser.add_argument(
        "--append",
        action="store_true",
        default=False,
        help="Write to ~/.ssh/config (default: print to stdout)",
    )
    ssh_config_parser.add_argument(
        "--remove",
        action="store_true",
        default=False,
        help="Remove sandbox entry from ~/.ssh/config",
    )
    ssh_config_parser.add_argument("--project", default=None, help="GCP project ID")
    ssh_config_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    ssh_config_parser.set_defaults(func=sandbox_ssh_config)

    # migrate
    migrate_parser = sandbox_subparsers.add_parser(
        "migrate", help="Run database migrations on the sandbox"
    )
    migrate_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    migrate_parser.add_argument("--project", default=None, help="GCP project ID")
    migrate_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    migrate_parser.set_defaults(func=sandbox_migrate)

    # restart-devserver
    restart_parser = sandbox_subparsers.add_parser(
        "restart-devserver", help="Restart the devserver on the sandbox"
    )
    restart_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    restart_parser.add_argument("--project", default=None, help="GCP project ID")
    restart_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    restart_parser.set_defaults(func=sandbox_restart_devserver)

    # exec
    exec_parser = sandbox_subparsers.add_parser(
        "exec", help="Run a command on the sandbox via SSH"
    )
    exec_parser.add_argument(
        "command",
        help="Command to execute on the sandbox (quote if it contains spaces)",
    )
    exec_parser.add_argument(
        "--name", default=None, help="Sandbox name (default: most recent)"
    )
    exec_parser.add_argument("--project", default=None, help="GCP project ID")
    exec_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    exec_parser.set_defaults(func=sandbox_exec)

    # hybrid
    hybrid_parser = sandbox_subparsers.add_parser(
        "hybrid",
        help="Use sandbox services with a local devserver (stops remote devserver, forwards service ports)",
    )
    hybrid_parser.add_argument(
        "name", nargs="?", default=None, help="Sandbox name (default: most recent)"
    )
    hybrid_parser.add_argument(
        "--stop",
        action="store_true",
        default=False,
        help="Exit hybrid mode (stops port forwarding, restarts sandbox devserver)",
    )
    hybrid_parser.add_argument("--project", default=None, help="GCP project ID")
    hybrid_parser.add_argument(
        "--zone",
        default=SANDBOX_DEFAULT_ZONE,
        help=f"GCE zone (default: {SANDBOX_DEFAULT_ZONE})",
    )
    hybrid_parser.set_defaults(func=sandbox_hybrid)

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
    sentry_ref = getattr(args, "sentry_ref", None)
    mode = args.mode
    spot = args.spot

    # Check if instance already exists
    existing_status = get_instance_status(name, project, zone)
    if existing_status is not None:
        console.failure(str(SandboxAlreadyExistsError(name)))
        exit(1)

    state = State()
    desc = f"branch: {branch}"
    if sentry_ref:
        desc += f", sentry: {sentry_ref}"
    with Status(
        lambda: console.warning(
            f"Creating sandbox '{name}' ({desc}, type: {machine_type})"
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
                sentry_ref=sentry_ref,
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
    else:
        ports = _parse_port_specs(args.ports)

    console.info(f"Connecting to sandbox '{name}'...")
    if ports:
        for local_port, remote_port in ports:
            if local_port == remote_port:
                console.info(f"  Forwarding port {local_port}")
            else:
                console.info(f"  Forwarding localhost:{local_port} -> sandbox:{remote_port}")
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
    sentry_ref = getattr(args, "sentry_ref", None) or ""

    desc = f"branch '{branch}'"
    if sentry_ref:
        desc += f", sentry: {sentry_ref}"
    console.info(f"Syncing sandbox '{name}' to {desc}...")

    sync_cmd = f"{SANDBOX_MAINTENANCE_SYNC_PATH} {branch}"
    if sentry_ref:
        sync_cmd += f" {sentry_ref}"

    try:
        result = ssh_command(name, project, zone, sync_cmd)
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

    ports = _parse_port_specs(args.ports)

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
        console.success(f"Port forwarding active (PID {proc.pid})")
        for local_port, remote_port in ports:
            if local_port == remote_port:
                console.info(f"  http://localhost:{local_port} -> sandbox:{remote_port}")
            else:
                console.info(f"  http://localhost:{local_port} -> sandbox:{remote_port}")
        console.info(f"\nStop with: devservices sandbox port-forward {name} --stop")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to start port forwarding: {e}")
        exit(1)


def sandbox_logs(args: Namespace) -> None:
    """View logs from a sandbox service."""
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

    service = args.service
    follow = args.follow
    lines = args.lines

    # Build the remote command
    if service in SANDBOX_SYSTEMD_SERVICES:
        unit = SANDBOX_SYSTEMD_SERVICES[service]
        if follow:
            remote_cmd = f"sudo journalctl -u {unit} -n {lines} -f"
        else:
            remote_cmd = f"sudo journalctl -u {unit} -n {lines} --no-pager"
    else:
        # Docker container — find by partial name match
        follow_flag = "-f " if follow else ""
        remote_cmd = (
            f"CONTAINER=$(sudo docker ps --format '{{{{.Names}}}}' | grep -i '{service}' | head -1) && "
            f'[ -n "$CONTAINER" ] && sudo docker logs --tail {lines} {follow_flag}"$CONTAINER" || '
            f"{{ echo 'No running container matching \"{service}\" found. Available containers:'; "
            f"sudo docker ps --format '{{{{.Names}}}}'; }}"
        )

    if follow:
        console.info(
            f"Tailing logs for '{service}' on sandbox '{name}' (Ctrl+C to stop)..."
        )
        try:
            proc = ssh_stream(name, project, zone, remote_cmd)
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
        except SandboxError as e:
            capture_exception(e, level="info")
            console.failure(f"Failed to stream logs: {e}")
            exit(1)
    else:
        try:
            result = ssh_command(name, project, zone, remote_cmd)
            if result.stdout:
                console.info(result.stdout.rstrip())
            if result.stderr:
                console.warning(result.stderr.rstrip())
        except SandboxError as e:
            capture_exception(e, level="info")
            console.failure(f"Failed to get logs: {e}")
            exit(1)


def sandbox_ssh_config(args: Namespace) -> None:
    """Generate or manage SSH config for a sandbox instance."""
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

    if args.remove:
        config_path = get_ssh_config_path()
        if remove_ssh_config_entry(config_path, name):
            console.success(f"Removed SSH config entry for '{name}'")
        else:
            console.info(f"No SSH config entry found for '{name}'")
        return

    status = get_instance_status(name, project, zone)
    if status is None:
        console.failure(str(SandboxNotFoundError(name)))
        exit(1)

    ports = _parse_port_specs(args.ports) if args.ports else None
    config_block = generate_ssh_config(name, project, zone, ports)

    if args.append:
        config_path = get_ssh_config_path()
        write_ssh_config_entry(config_path, name, config_block)
        console.success(f"SSH config entry written to {config_path}")
        console.info(f"\nYou can now connect with:")
        console.info(f"  ssh {name}")
        console.info(f"  VS Code: code --remote ssh-remote+{name} /path/on/sandbox")
    else:
        console.info(config_block.rstrip())


def sandbox_migrate(args: Namespace) -> None:
    """Run database migrations on the sandbox."""
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

    console.info(f"Running migrations on sandbox '{name}'...")
    try:
        result = ssh_command(
            name, project, zone, "cd /opt/getsentry && make apply-migrations"
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                console.info(f"  {line}")
        console.success(f"Migrations completed successfully on '{name}'")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to run migrations: {e}")
        exit(1)


def sandbox_restart_devserver(args: Namespace) -> None:
    """Restart the devserver on the sandbox."""
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

    try:
        ssh_command(name, project, zone, "sudo systemctl restart sandbox-devserver")
        console.success(f"Devserver restarted on '{name}'")

        result = ssh_command(
            name, project, zone, "sudo systemctl is-active sandbox-devserver"
        )
        if result.stdout:
            console.info(f"  Service status: {result.stdout.strip()}")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to restart devserver: {e}")
        exit(1)


def sandbox_exec(args: Namespace) -> None:
    """Run a command on the sandbox via SSH."""
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

    try:
        result = ssh_command(name, project, zone, args.command)
        if result.stdout:
            console.info(result.stdout.rstrip())
        if result.stderr:
            console.warning(result.stderr.rstrip())
    except SandboxOperationError as e:
        if e.stderr:
            console.warning(e.stderr)
        exit(e.returncode)
    except SandboxError as e:
        console.failure(f"Failed to execute command: {e}")
        exit(1)


def sandbox_hybrid(args: Namespace) -> None:
    """Toggle hybrid mode: local devserver with remote sandbox services."""
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

    if args.stop:
        # Exit hybrid mode: stop port forwarding, restart devserver
        _stop_port_forward(name, state, console)

        console.info("Starting sandbox devserver...")
        try:
            ssh_command(
                name, project, zone, "sudo systemctl start sandbox-devserver"
            )
            console.success(f"Hybrid mode stopped for '{name}'")
            console.info(f"Connect with: devservices sandbox ssh {name}")
        except SandboxError as e:
            capture_exception(e, level="info")
            console.failure(f"Failed to restart devserver: {e}")
            exit(1)
        return

    # Enter hybrid mode: stop devserver, forward service ports
    console.info(f"Entering hybrid mode for '{name}'...")

    # 1. Stop remote devserver
    try:
        ssh_command(
            name, project, zone, "sudo systemctl stop sandbox-devserver"
        )
        console.info("Stopped sandbox devserver")
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to stop devserver: {e}")
        exit(1)

    # 2. Stop any existing port forwarding
    existing_pid = state.get_port_forward_pid(name)
    if existing_pid and is_port_forward_running(existing_pid):
        stop_port_forward(existing_pid)
        state.update_port_forward_pid(name, None)

    # 3. Forward service ports
    ports = list(SANDBOX_PORT_PROFILES["services"])
    try:
        proc = start_port_forward(name, project, zone, ports)
        state.update_port_forward_pid(name, proc.pid)
    except SandboxError as e:
        capture_exception(e, level="info")
        console.failure(f"Failed to start port forwarding: {e}")
        # Try to restart devserver since we stopped it
        try:
            ssh_command(
                name, project, zone, "sudo systemctl start sandbox-devserver"
            )
        except SandboxError:
            pass
        exit(1)

    console.success(f"Hybrid mode active for '{name}'")
    console.info("Forwarded service ports:")
    for local_port, remote_port in ports:
        console.info(f"  localhost:{local_port} -> sandbox:{remote_port}")
    console.info(f"\nStart your local devserver:")
    console.info(f"  devservices serve")
    console.info(f"\nExit hybrid mode:")
    console.info(f"  devservices sandbox hybrid {name} --stop")
