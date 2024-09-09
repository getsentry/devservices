from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("start", help="Start a service and its dependencies")
    parser.add_argument("service_name", help="Name of the service to start")
    parser.set_defaults(func=start)


def start(args: Namespace) -> None:
    """Start a service and its dependencies."""
    service_name = args.service_name

    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    # Implementation here
    print(f"Starting service: {service.name}")
    # Use docker_compose utility to start the service
