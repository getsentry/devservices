from __future__ import annotations

import os
import shutil
from argparse import _SubParsersAction
from argparse import ArgumentParser
from argparse import Namespace

from devservices.constants import DEVSERVICES_CACHE_DIR


def add_parser(subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parser = subparsers.add_parser("purge", help="Purge the local devservices cache")
    parser.set_defaults(func=purge)


def purge(args: Namespace) -> None:
    """Purge the local devservices cache."""
    if os.path.exists(DEVSERVICES_CACHE_DIR):
        try:
            shutil.rmtree(DEVSERVICES_CACHE_DIR)
        except PermissionError as e:
            print(f"Failed to purge cache: {e}")
            exit(1)
    print("The local devservices cache has been purged")
