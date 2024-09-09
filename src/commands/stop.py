from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("stop", help="Stop a service and its dependencies")
    parser.add_argument("service_name", help="Name of the service to stop")
    parser.set_defaults(func=stop)


def stop(args: Namespace) -> None:
    """Stop a service and its dependencies."""
    service_name = args.service_name

    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)

    # Implementation here
    print(f"Stopping service: {service.name}")
    # Use docker_compose utility to stop the service
