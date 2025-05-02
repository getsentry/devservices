from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.commands.down import bring_down_service
from devservices.commands.up import up
from devservices.exceptions import CannotToggleNonRemoteServiceError
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("toggle", help="Toggle how a service is run")
    parser.add_argument(
        "service_name", help="Name of the service to toggle", nargs="?", default=None
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "runtime",
        help="Runtime to use for the service",
        choices=[runtime.value for runtime in ServiceRuntime],
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=toggle)


def toggle(args: Namespace) -> None:
    """Toggle how a service is run."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices toggle snuba`) or run the command from a directory with a devservices configuration."
        )
        return
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        return

    desired_runtime = args.runtime
    state = State()
    current_runtime = state.get_service_runtime(service.name)
    if desired_runtime is None:
        desired_runtime = get_opposite_runtime(current_runtime).value
    if current_runtime == desired_runtime:
        console.warning(
            f"{service.name} is already running in {desired_runtime} runtime"
        )
        return
    if desired_runtime == ServiceRuntime.LOCAL:
        try:
            handle_transition_to_local_runtime(service)
        except CannotToggleNonRemoteServiceError as e:
            capture_exception(e)
            console.failure(f"{str(e)}")
            exit(1)
    elif desired_runtime == ServiceRuntime.CONTAINERIZED:
        handle_transition_to_containerized_runtime(service)

    final_runtime = state.get_service_runtime(service.name)
    if final_runtime == desired_runtime:
        console.success(f"{service.name} is now running in {desired_runtime} runtime")


def handle_transition_to_local_runtime(service_to_transition: Service) -> None:
    """Handle the transition to a local runtime for a service."""
    console = Console()
    state = State()

    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)

    # If the service is already running standalone, we can just update the runtime
    if service_to_transition.name in active_services:
        state.update_service_runtime(service_to_transition.name, ServiceRuntime.LOCAL)
        console.success(
            f"{service_to_transition.name} is now running in {ServiceRuntime.LOCAL.value} runtime"
        )
        return

    for active_service_name in active_services:
        active_service = find_matching_service(active_service_name)
        starting_active_modes = set(
            state.get_active_modes_for_service(
                active_service_name, StateTables.STARTING_SERVICES
            )
        )
        started_active_modes = set(
            state.get_active_modes_for_service(
                active_service_name, StateTables.STARTED_SERVICES
            )
        )
        active_modes = starting_active_modes.union(started_active_modes)
        dependency_graph = construct_dependency_graph(
            active_service, list(active_modes)
        )
        if service_to_transition.name in [node.name for node in dependency_graph.graph]:
            service_to_transition_dependency_config = (
                active_service.config.dependencies.get(service_to_transition.name, None)
            )
            if (
                service_to_transition_dependency_config is None
                or service_to_transition_dependency_config.remote is None
            ):
                raise CannotToggleNonRemoteServiceError(service_to_transition.name)
            bring_down_containerized_service(
                service_to_transition,
                [service_to_transition_dependency_config.remote.mode],
            )
            break
    state.update_service_runtime(service_to_transition.name, ServiceRuntime.LOCAL)


def handle_transition_to_containerized_runtime(service: Service) -> None:
    """Handle the transition to a containerized runtime for a service."""
    console = Console()
    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    if service.name in active_services:
        console.warning(f"{service.name} is running, please stop it first")
        return
    dependent_services = find_dependent_services(service, active_services)
    state.update_service_runtime(service.name, ServiceRuntime.CONTAINERIZED)
    if len(dependent_services.keys()) > 0:
        # It's important that the state is updated before the dependent services are restarted
        restart_dependent_services(service.name, dependent_services)


def find_dependent_services(
    service: Service, active_services: set[str]
) -> dict[str, list[str]]:
    """Find all dependent services for a given service and the modes for which they depend on the given service."""
    state = State()
    dependent_services: dict[str, list[str]] = dict()
    for active_service_name in active_services:
        active_service = find_matching_service(active_service_name)
        starting_active_modes = set(
            state.get_active_modes_for_service(
                active_service_name, StateTables.STARTING_SERVICES
            )
        )
        started_active_modes = set(
            state.get_active_modes_for_service(
                active_service_name, StateTables.STARTED_SERVICES
            )
        )
        active_modes = starting_active_modes.union(started_active_modes)
        for active_mode in active_modes:
            dependency_graph = construct_dependency_graph(active_service, [active_mode])
            if service.name in [node.name for node in dependency_graph.graph]:
                current_dependent_modes = dependent_services.get(
                    active_service_name, []
                )
                current_dependent_modes.append(active_mode)
                dependent_services[active_service_name] = current_dependent_modes
    return dependent_services


def restart_dependent_services(
    service_name: str, dependent_services: dict[str, list[str]]
) -> None:
    """Restart all relevant modes of all dependent services to ensure the service is running in a containerized runtime."""
    console = Console()
    with Status(
        on_start=lambda: console.warning(
            f"Restarting dependent services to ensure {service_name} is running in a {ServiceRuntime.CONTAINERIZED.value} runtime"
        ),
    ) as status:
        for dependent_service in dependent_services:
            for mode in dependent_services[dependent_service]:
                status.info(f"Restarting {dependent_service} in mode {mode}")
                args = Namespace(
                    service_name=dependent_service,
                    mode=mode,
                    debug=False,
                )
                try:
                    up(args)
                except SystemExit:
                    status.failure(
                        f"Failed to restart {dependent_service} in mode {mode}"
                    )
                    exit(1)
        status.success("Successfully restarted dependent services")


def bring_down_containerized_service(
    service: Service,
    active_modes: list[str],
) -> None:
    """Bring down a containerized service running within another service."""
    console = Console()
    exclude_local = True
    with Status(
        lambda: console.warning(f"Stopping {service.name}"),
    ) as status:
        mode_dependencies = set()
        for active_mode in active_modes:
            active_mode_dependencies = service.config.modes.get(active_mode, [])
            mode_dependencies.update(active_mode_dependencies)
        try:
            remote_dependencies = install_and_verify_dependencies(
                service, modes=active_modes
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)
        try:
            remote_dependencies = get_non_shared_remote_dependencies(
                service, remote_dependencies, exclude_local
            )
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)
        try:
            bring_down_service(
                service,
                remote_dependencies,
                sorted(list(mode_dependencies)),
                exclude_local,
                status,
            )
        except DockerComposeError as dce:
            capture_exception(dce, level="info")
            status.failure(f"Failed to stop {service.name}: {dce.stderr}")
            exit(1)


def get_opposite_runtime(current_runtime: ServiceRuntime) -> ServiceRuntime:
    if current_runtime == ServiceRuntime.CONTAINERIZED:
        return ServiceRuntime.LOCAL
    else:
        return ServiceRuntime.CONTAINERIZED
