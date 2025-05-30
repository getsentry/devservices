from __future__ import annotations

import concurrent.futures
import os
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception
from sentry_sdk import set_context
from sentry_sdk import start_span

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import PROGRAMS_CONF_FILE_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ContainerHealthcheckFailedError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ModeDoesNotExistError
from devservices.exceptions import ServiceNotFoundError
from devservices.exceptions import SupervisorError
from devservices.utils.console import Console
from devservices.utils.console import Status
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker import check_all_containers_healthy
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.docker_compose import get_container_names_for_project
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import run_cmd
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from devservices.utils.supervisor import SupervisorManager


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("up", help="Bring up a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to bring up", nargs="?", default=None
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--mode",
        help="Mode to use for the service",
        default="default",
    )
    parser.add_argument(
        "--exclude-local",
        help="Exclude dependencies with local runtime from being started",
        action="store_true",
        default=False,
    )
    parser.set_defaults(func=up)


def up(args: Namespace, existing_status: Status | None = None) -> None:
    """Bring up a service and its dependencies."""
    console = Console()
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices up sentry`) or run the command from a directory with a devservices configuration."
        )
        exit(1)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)

    modes = service.config.modes
    mode = args.mode
    exclude_local = getattr(args, "exclude_local", False)

    state = State()

    with Status(
        lambda: (
            console.warning(f"Starting '{service.name}' in mode: '{mode}'")
            if existing_status is None
            else existing_status.warning(f"Starting '{service.name}' in mode: '{mode}'")
        ),
        lambda: (
            console.success(f"{service.name} started")
            if existing_status is None
            else existing_status.success(f"{service.name} started")
        ),
    ) as status:
        local_runtime_dependency_names = set()
        with start_span(
            op="service.dependencies.check", name="Check local runtime dependencies"
        ) as span:
            services_with_local_runtime = state.get_services_by_runtime(
                ServiceRuntime.LOCAL
            )
            for service_with_local_runtime in services_with_local_runtime:
                if (
                    mode in modes
                    and service_with_local_runtime != service.name
                    and service_with_local_runtime in modes[mode]
                ):
                    local_runtime_dependency_names.add(service_with_local_runtime)
                    if exclude_local:
                        status.warning(
                            f"Skipping '{service_with_local_runtime}' as it is set to run locally"
                        )
            span.set_data("service_name", service.name)
            span.set_data("mode", mode)
            span.set_data(
                "local_runtime_dependency_count", len(local_runtime_dependency_names)
            )
            span.set_data(
                "local_runtime_dependency_names", local_runtime_dependency_names
            )

        context_name = f"local_runtime_dependencies.{service.name}"
        set_context(
            context_name,
            {
                "service_name": service.name,
                "mode": mode,
                "exclude_local": exclude_local,
                "count": len(local_runtime_dependency_names),
                "names": list(local_runtime_dependency_names),
            },
        )

        remote_dependencies = _install_service_dependencies(service, mode, status)
        _create_devservices_network()
        # Add the service to the starting services table
        state.update_service_entry(service.name, mode, StateTables.STARTING_SERVICES)
        mode_dependencies = modes[mode]
        for service_with_local_runtime in services_with_local_runtime:
            if (
                service_with_local_runtime
                in [dep.service_name for dep in remote_dependencies]
                and service_with_local_runtime not in local_runtime_dependency_names
            ):
                local_runtime_dependency_names.add(service_with_local_runtime)
                if exclude_local:
                    status.warning(
                        f"Skipping '{service_with_local_runtime}' as it is set to run locally"
                    )
        # We want to ignore any dependencies that are set to run locally
        mode_dependencies = [
            dep for dep in mode_dependencies if dep not in services_with_local_runtime
        ]

        supervisor_programs = [
            dep
            for dep in mode_dependencies
            if dep in service.config.dependencies
            and service.config.dependencies[dep].dependency_type
            == DependencyType.SUPERVISOR
        ]

        remote_dependencies = {
            dep
            for dep in remote_dependencies
            if dep.service_name not in services_with_local_runtime
        }
        if not exclude_local and len(local_runtime_dependency_names) > 0:
            status.warning("Starting dependencies with local runtimes...")
            for local_runtime_dependency_name in local_runtime_dependency_names:
                up(
                    Namespace(
                        service_name=local_runtime_dependency_name,
                        mode="default",  # We intentionally don't use the mode from the parent command here
                        exclude_local=True,  # TODO: This should be False (or maybe whatever the parent command is set to)
                    ),
                    status,
                )
            status.warning(f"Continuing with service '{service.name}'")
        with start_span(
            op="service.containers.start", name="Start service containers"
        ) as span:
            span.set_data("service_name", service.name)
            span.set_data("mode", mode)
            span.set_data("exclude_local", exclude_local)
            try:
                bring_up_docker_compose_services(
                    service, [mode], remote_dependencies, mode_dependencies, status
                )
            except DockerComposeError as dce:
                capture_exception(dce, level="info")
                status.failure(f"Failed to start {service.name}: {dce.stderr}")
                exit(1)
        with start_span(
            op="service.supervisor.start", name="Start supervisor programs"
        ) as span:
            span.set_data("service_name", service.name)
            span.set_data("supervisor_programs", supervisor_programs)
            try:
                bring_up_supervisor_programs(service, supervisor_programs, status)
            except SupervisorError as se:
                capture_exception(se, level="info")
                status.failure(str(se))
                exit(1)

    state.remove_service_entry(service.name, StateTables.STARTING_SERVICES)
    state.update_service_entry(service.name, mode, StateTables.STARTED_SERVICES)


def _install_service_dependencies(
    service: Service, mode: str, status: Status
) -> set[InstalledRemoteDependency]:
    with start_span(
        op="service.dependencies.install", name="Install dependencies"
    ) as span:
        status.info("Retrieving dependencies")
        span.set_data("service_name", service.name)
        span.set_data("mode", mode)
        try:
            remote_dependencies = install_and_verify_dependencies(
                service, force_update_dependencies=True, modes=[mode]
            )
            span.set_data("remote_dependency_count", len(remote_dependencies))
            return remote_dependencies
        except DependencyError as de:
            capture_exception(de)
            status.failure(
                f"{str(de)}. If this error persists, try running `devservices purge`"
            )
            exit(1)
        except ModeDoesNotExistError as mde:
            status.failure(str(mde))
            exit(1)


def _create_devservices_network() -> None:
    with start_span(
        op="service.network.create", name="Create devservices network"
    ) as span:
        try:
            subprocess.run(
                ["docker", "network", "create", "devservices"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            span.set_data("network_created", True)
        except subprocess.CalledProcessError:
            # Network already exists, ignore the error
            span.set_data("network_created", False)


def _pull_dependency_images(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> None:
    with start_span(op="service.images.pull", name="Pull dependency images") as span:
        span.set_data("command", cmd.full_command)
        run_cmd(cmd.full_command, current_env, retries=4)
        for dependency in cmd.services:
            status.info(f"Pulled image for {dependency}")


def _bring_up_dependency(
    cmd: DockerComposeCommand, current_env: dict[str, str], status: Status
) -> None:
    with start_span(
        op="service.containers.up", name="Bring up dependency containers"
    ) as span:
        span.set_data("command", cmd.full_command)
        span.set_data("services", cmd.services)
        for dependency in cmd.services:
            status.info(f"Starting {dependency}")
        run_cmd(cmd.full_command, current_env)


def bring_up_docker_compose_services(
    service: Service,
    modes: list[str],
    remote_dependencies: set[InstalledRemoteDependency],
    mode_dependencies: list[str],
    status: Status,
) -> None:
    relative_local_dependency_directory = os.path.relpath(
        os.path.join(DEVSERVICES_DEPENDENCIES_CACHE_DIR, DEPENDENCY_CONFIG_VERSION),
        service.repo_path,
    )
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    # Set the environment variable for the local dependencies directory to be used by docker compose
    current_env = os.environ.copy()
    current_env[
        DEVSERVICES_DEPENDENCIES_CACHE_DIR_KEY
    ] = relative_local_dependency_directory
    dependency_graph = construct_dependency_graph(service, modes=modes)
    starting_order = dependency_graph.get_starting_order()
    sorted_remote_dependencies = sorted(
        remote_dependencies,
        key=lambda dep: starting_order.index(
            DependencyNode(
                name=dep.service_name, dependency_type=DependencyType.SERVICE
            )
        ),
    )

    # Pull all images in parallel
    status.info("Pulling images")
    pull_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=sorted_remote_dependencies,
        current_env=current_env,
        command="pull",
        options=[],
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    with concurrent.futures.ThreadPoolExecutor() as pull_dependency_executor:
        futures = [
            pull_dependency_executor.submit(
                _pull_dependency_images, cmd, current_env, status
            )
            for cmd in pull_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            _ = future.result()

    # Bring up all necessary containers
    up_commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=sorted_remote_dependencies,
        current_env=current_env,
        command="up",
        options=["-d"],
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )

    containers_to_check = []
    with concurrent.futures.ThreadPoolExecutor() as up_dependency_executor:
        futures = [
            up_dependency_executor.submit(
                _bring_up_dependency, cmd, current_env, status
            )
            for cmd in up_commands
        ]
        for future in concurrent.futures.as_completed(futures):
            _ = future.result()

    for cmd in up_commands:
        try:
            container_names = get_container_names_for_project(
                cmd.project_name, cmd.config_path, cmd.services
            )
            containers_to_check.extend(container_names)
        except DockerComposeError as dce:
            status.failure(
                f"Failed to get containers to healthcheck for {cmd.project_name}: {dce.stderr}"
            )
            exit(1)
    try:
        check_all_containers_healthy(status, containers_to_check)
    except ContainerHealthcheckFailedError as e:
        status.failure(str(e))
        exit(1)


def bring_up_supervisor_programs(
    service: Service, supervisor_programs: list[str], status: Status
) -> None:
    if len(supervisor_programs) == 0:
        return
    if not os.path.samefile(os.getcwd(), service.repo_path):
        status.warning(
            f"Cannot bring up supervisor programs from outside the service repository. Please run the command from the service repository ({service.repo_path})"
        )
        return
    programs_config_path = os.path.join(
        service.repo_path, f"{DEVSERVICES_DIR_NAME}/{PROGRAMS_CONF_FILE_NAME}"
    )

    manager = SupervisorManager(
        programs_config_path,
        service_name=service.name,
    )

    status.info("Starting supervisor daemon")
    manager.start_supervisor_daemon()

    for program in supervisor_programs:
        status.info(f"Starting {program}")
        manager.start_process(program)
