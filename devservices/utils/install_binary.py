from __future__ import annotations

import os
import shutil
import tempfile
from urllib.request import urlretrieve

from devservices.constants import BINARY_PERMISSIONS
from devservices.exceptions import BinaryInstallError
from devservices.utils.console import Console
from devservices.utils.retry import retry


def install_binary(
    binary_name: str,
    exec_path: str,
    version: str,
    url: str,
) -> None:
    console = Console()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_file = os.path.join(temp_dir, binary_name)

        console.info(f"Downloading {binary_name} {version} from {url}...")
        try:
            retry(
                lambda: urlretrieve(url, temp_file),
                retries=3,
                delay=1.0,
                on_retry=lambda e, remaining: console.warning(
                    f"Download failed. Retrying in 1 seconds... ({remaining} retries left)"
                ),
            )
        except Exception as e:
            raise BinaryInstallError(
                f"Failed to download {binary_name} after 3 attempts: {e}"
            ) from e

        try:
            os.chmod(temp_file, BINARY_PERMISSIONS)
        except (PermissionError, FileNotFoundError) as e:
            raise BinaryInstallError(
                f"Failed to set executable permissions: {e}"
            ) from e

        try:
            shutil.move(temp_file, exec_path)
        except (PermissionError, FileNotFoundError) as e:
            raise BinaryInstallError(
                f"Failed to move {binary_name} binary to {exec_path}: {e}"
            ) from e
