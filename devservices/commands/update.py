from __future__ import annotations

import platform
import sys
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace
from importlib import metadata

from devservices.commands.check_for_update import check_for_update
from devservices.constants import DEVSERVICES_DOWNLOAD_URL
from devservices.exceptions import BinaryInstallError
from devservices.exceptions import DevservicesUpdateError
from devservices.utils.install_binary import install_binary


def is_in_virtualenv() -> bool:
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def update_version(exec_path: str, latest_version: str) -> None:
    system = platform.system().lower()
    url = f"{DEVSERVICES_DOWNLOAD_URL}/{latest_version}/devservices-{system}"
    try:
        install_binary("devservices", exec_path, latest_version, url)
    except BinaryInstallError as e:
        raise DevservicesUpdateError(f"Failed to update devservices: {e}")

    print(f"Devservices {latest_version} updated successfully")


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "update", help="update devservices to the latest version"
    )
    parser.set_defaults(func=update)


def update(args: Namespace) -> None:
    current_version = metadata.version("devservices")
    latest_version = check_for_update(current_version)

    if latest_version is None:
        raise DevservicesUpdateError("Failed to check for updates.")

    if latest_version == current_version:
        print("You're already on the latest version.")
        return

    print(f"A new version of devservices is available: {latest_version}")

    if is_in_virtualenv():
        print("You are running in a virtual environment.")
        print(
            "To update, please update your requirements.txt or requirements-dev.txt file with the new version."
        )
        print(
            f"For example, update the line in requirements.txt to: devservices=={latest_version}"
        )
        print("Then, run: pip install --update -r requirements.txt")
        return

    print("Upgrading to the latest version...")
    update_version(sys.executable, latest_version)