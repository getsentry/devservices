from __future__ import annotations

import argparse
import atexit
import os
import re
import subprocess
from importlib import metadata
from typing import cast

import sentry_sdk
from packaging import version
from sentry_sdk.integrations.argv import ArgvIntegration

from devservices.commands import list_dependencies
from devservices.commands import list_services
from devservices.commands import logs
from devservices.commands import start
from devservices.commands import status
from devservices.commands import stop
from devservices.constants import MINIMUM_DOCKER_COMPOSE_VERSION
from devservices.exceptions import DockerComposeError

sentry_environment = (
    "development" if os.environ.get("IS_DEV", default=False) else "production"
)

sentry_sdk.init(
    dsn="https://56470da7302c16e83141f62f88e46449@o1.ingest.us.sentry.io/4507946704961536",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    enable_tracing=True,
    integrations=[ArgvIntegration()],
    environment=sentry_environment,
)


def check_docker_compose_version() -> None:
    cmd = ["docker", "compose", "version", "--short"]
    try:
        # Run the docker compose version command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        # Extract the version number from the output
        version_output = result.stdout.strip()

        # Use regex to find the version number
        pattern = r"^(\d+\.\d+\.\d+)"

        match = re.search(pattern, version_output)
        if match:
            # There is a chance that Any type is returned, so cast this
            docker_compose_version = cast(str, match.group(1))
        else:
            docker_compose_version = None

    except subprocess.CalledProcessError as e:
        raise DockerComposeError(
            command=" ".join(cmd),
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        )

    if docker_compose_version is None:
        print("Unable to detect docker compose version")
        exit(1)
    elif version.parse(docker_compose_version) < version.parse(
        MINIMUM_DOCKER_COMPOSE_VERSION
    ):
        print("Docker compose version unsupported, please upgrade to >= 2.21.0")
        exit(1)


@atexit.register
def cleanup() -> None:
    sentry_sdk.flush()


def main() -> None:
    check_docker_compose_version()
    parser = argparse.ArgumentParser(
        prog="devservices",
        description="CLI tool for managing service dependencies.",
        usage="devservices [-h] [--version] COMMAND ...",
    )
    parser.add_argument(
        "--version", action="version", version=metadata.version("devservices")
    )

    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="")

    # Add subparsers for each command
    start.add_parser(subparsers)
    stop.add_parser(subparsers)
    list_dependencies.add_parser(subparsers)
    list_services.add_parser(subparsers)
    status.add_parser(subparsers)
    logs.add_parser(subparsers)

    args = parser.parse_args()

    if args.command:
        # Call the appropriate function based on the command
        with sentry_sdk.start_transaction(op="command", name=args.command):
            args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
