from __future__ import annotations

import os
import subprocess
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from constants import DEVSERVICES_DIR_NAME
from constants import DOCKER_COMPOSE_FILE_NAME
from utils.services import find_matching_service


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("stop", help="Stop a service and its dependencies")
    parser.add_argument(
        "service_name", help="Name of the service to start", nargs="?", default=None
    )
    parser.set_defaults(func=stop)


def stop(args: Namespace) -> None:
    """Stop a service and its dependencies."""
    service_name = args.service_name
    try:
        service = find_matching_service(service_name)
    except Exception as e:
        print(e)
        exit(1)
    modes = service.config.modes
    # TODO: allow custom modes to be used
    mode_to_start = "default"
    mode_dependencies = modes[mode_to_start]
    service_config_file_path = os.path.join(
        service.repo_path, DEVSERVICES_DIR_NAME, DOCKER_COMPOSE_FILE_NAME
    )
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            service_config_file_path,
            "down",
        ]
        + mode_dependencies,
        check=False,
    )
