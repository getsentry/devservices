from __future__ import annotations

import os
import pty
import shlex
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ServiceNotFoundError
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.console import Console
from devservices.utils.services import find_matching_service
from devservices.utils.state import State
from devservices.utils.state import StateTables
from devservices.utils.supervisor import SupervisorManager


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "foreground", help="Run a service's program in the foreground"
    )
    parser.add_argument(
        "program_name", help="Name of the program to run in the foreground"
    )
    parser.set_defaults(func=foreground)


def foreground(args: Namespace) -> None:
    """Run a service's program in the foreground."""
    console = Console()
    program_name = args.program_name
    try:
        service = find_matching_service()
    except ConfigNotFoundError as e:
        capture_exception(e, level="info")
        console.failure(
            f"{str(e)}. Please specify a service (i.e. `devservices down sentry`) or run the command from a directory with a devservices configuration."
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
    if program_name not in service.config.dependencies:
        console.failure(
            f"Program {program_name} does not exist in the service's config"
        )
        return
    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    if service.name not in active_services:
        console.warning(f"{service.name} is not running")
        return
    active_starting_modes = state.get_active_modes_for_service(
        service.name, StateTables.STARTING_SERVICES
    )
    active_started_modes = state.get_active_modes_for_service(
        service.name, StateTables.STARTED_SERVICES
    )
    active_modes = active_starting_modes or active_started_modes
    mode_dependencies = set()
    for active_mode in active_modes:
        active_mode_dependencies = modes.get(active_mode, [])
        mode_dependencies.update(active_mode_dependencies)

    supervisor_programs = [
        dep
        for dep in mode_dependencies
        if dep in service.config.dependencies
        and service.config.dependencies[dep].dependency_type
        == DependencyType.SUPERVISOR
    ]

    if program_name not in supervisor_programs:
        console.failure(
            f"Program {program_name} is not running in any active modes of {service.name}"
        )
        return

    config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )

    try:
        manager = SupervisorManager(service.name, config_file_path)
    except SupervisorConfigError as e:
        capture_exception(e, level="info")
        return

    try:
        program_command = manager.get_program_command(program_name)
    except SupervisorConfigError as e:
        capture_exception(e, level="info")
        console.failure(f"Error when getting program command: {str(e)}")
        return

    try:
        # Stop the supervisor process before running in foreground
        console.info(f"Stopping {program_name} in supervisor")
        manager.stop_process(program_name)
        console.info(f"Starting {program_name} in foreground")
        argv = shlex.split(program_command)

        # Run the process in foreground
        pty.spawn(argv)
    except SupervisorProcessError as e:
        capture_exception(e)
        console.failure(f"Error stopping {program_name} in supervisor: {str(e)}")
    except (OSError, FileNotFoundError, PermissionError) as e:
        capture_exception(e)
        console.failure(f"Error running {program_name} in foreground: {str(e)}")

    try:
        console.info(f"Restarting {program_name} in background")
        manager.start_process(program_name)
    except SupervisorProcessError as e:
        capture_exception(e)
        console.failure(f"Error restarting {program_name} in background: {str(e)}")
