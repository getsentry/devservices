from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace, _SubParsersAction

import yaml

from utils.config import load_devservices_config
from utils.devenv import get_code_root


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
    if not service_name:
        current_dir = os.getcwd()
        service_path = os.path.join(current_dir)
    else:
        code_root = get_code_root()
        service_path = os.path.join(code_root, service_name)
    try:
        config = load_devservices_config(service_path)
    except FileNotFoundError:
        print(
            f'Service "{service_name}" not found, or devservices config does not exist'
        )
        return
    except yaml.YAMLError as e:
        raise Exception(f"Failed to load service config: {e}")

    dependencies = config.devservices_config.dependencies

    if not dependencies:
        print(f"No dependencies found for {service_name}")
        return

    print(f"Dependencies of {config.devservices_config.service_name}:")
    for dependency_key, dependency_info in dependencies.items():
        print("-", dependency_key, ":", dependency_info.description)
