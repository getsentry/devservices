from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.utils.console import Console
from devservices.utils.devenv import get_coderoot
from devservices.utils.services import get_local_services
from devservices.utils.state import State


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "list-services", help="List the services installed locally", aliases=["ls"]
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Show all services, including stopped ones",
    )
    parser.set_defaults(func=list_services)


def list_services(args: Namespace) -> None:
    """List the services installed locally."""
    console = Console()
    # Get all of the services installed locally
    coderoot = get_coderoot()
    services = get_local_services(coderoot)
    state = State()
    running_services = state.get_started_services()

    if not services:
        console.warning("No services found")
        return

    services_to_show = (
        services if args.all else [s for s in services if s.name in running_services]
    )

    if args.all:
        console.info("Services installed locally:")
    else:
        console.info("Running services:")

    for service in services_to_show:
        status = "running" if service.name in running_services else "stopped"
        active_modes = state.get_active_modes_for_service(service.name)
        console.info(f"- {service.name}")
        console.info(f"  modes: {active_modes}")
        console.info(f"  status: {status}")
        console.info(f"  location: {service.repo_path}")

    if not args.all:
        stopped_count = len(services) - len(services_to_show)
        if stopped_count > 0:
            console.info(
                f"\n{stopped_count} stopped service(s) not shown. Use --all/-a to see them."
            )
