from __future__ import annotations

from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from utils.devenv import get_coderoot
from utils.services import get_local_services


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "list-services", help="List the services installed locally"
    )
    parser.set_defaults(func=list_services)


def list_services(args: Namespace) -> None:
    """List the services installed locally."""

    # Get all of the services installed locally
    coderoot = get_coderoot()
    services = get_local_services(coderoot)

    if not services:
        print("No services found")
        return

    print("Services installed locally:")
    for service in services:
        print("-", service.name, f"({service.repo_path})")
