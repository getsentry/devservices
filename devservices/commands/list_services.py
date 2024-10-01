from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.utils.devenv import get_coderoot
from devservices.utils.docker_compose import get_active_docker_compose_projects
from devservices.utils.services import get_local_services


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

    # Get all of the services installed locally
    coderoot = get_coderoot()
    services = get_local_services(coderoot)
    running_projects = get_active_docker_compose_projects()

    if not services:
        print("No services found")
        return

    services_to_show = (
        services if args.all else [s for s in services if s.name in running_projects]
    )

    if args.all:
        print("Services installed locally:")
    else:
        print("Running services:")

    for service in services_to_show:
        status = "running" if service.name in running_projects else "stopped"
        print(f"- {service.name}")
        print(f"  status: {status}")
        print(f"  location: {service.repo_path}")

    if not args.all:
        stopped_count = len(services) - len(services_to_show)
        if stopped_count > 0:
            print(
                f"\n{stopped_count} stopped service(s) not shown. Use --all/-a to see them."
            )
