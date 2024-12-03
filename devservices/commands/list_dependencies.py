from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from sentry_sdk import capture_exception

from devservices.exceptions import ConfigError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.console import Console
from devservices.utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "list-dependencies", help="List the dependencies of a service"
    )
    parser.add_argument(
        "service_name",
        help="Name of the service to list the dependencies of",
        nargs="?",
        default=None,
    )
    parser.set_defaults(func=list_dependencies)


def list_dependencies(args: Namespace) -> None:
    """List the dependencies of a service."""
    console = Console()
    service_name = args.service_name

    try:
        service = find_matching_service(service_name)
    except ConfigError as e:
        capture_exception(e)
        console.failure(str(e))
        exit(1)
    except ServiceNotFoundError as e:
        console.failure(str(e))
        exit(1)

    dependencies = service.config.dependencies

    if not dependencies:
        console.info(f"No dependencies found for {service.name}")
        return

    console.info(f"Dependencies of {service.name}:")
    for dependency_key, dependency_info in dependencies.items():
        console.info("- " + dependency_key + ": " + dependency_info.description)
