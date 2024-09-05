from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from configs.service_config import load_service_config
from services import find_matching_service


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
    service_name = args.service_name

    repo_path = None
    if service_name is not None:
        try:
            repo_path = find_matching_service(service_name).repo_path
        except Exception as e:
            print(e)
            return

    # Note: If no service name is provided, the current directory is assumed to be the location of the service
    config = load_service_config(repo_path)
    dependencies = config.service_config.dependencies

    if not dependencies:
        print(f"No dependencies found for {config.service_config.service_name}")
        return

    print(f"Dependencies of {config.service_config.service_name}:")
    for dependency_key, dependency_info in dependencies.items():
        print("-", dependency_key, ":", dependency_info.description)
