from __future__ import annotations

import os
import shutil
import tempfile
import time
from urllib.request import urlretrieve

from devservices.constants import BINARY_PERMISSIONS
from devservices.exceptions import BinaryInstallError
from devservices.utils.console import Console


def install_binary(
    binary_name: str,
    exec_path: str,
    version: str,
    url: str,
) -> None:
    console = Console()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = os.path.join(temp_dir, binary_name)

        # Download the binary with retries
        max_retries = 3
        retry_delay_seconds = 1
        console.info(f"Downloading {binary_name} {version} from {url}...")
        for attempt in range(max_retries):
            try:
                urlretrieve(url, temp_file)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    console.warning(
                        f"Download failed. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt + 1}/{max_retries - 1})"
                    )
                    time.sleep(retry_delay_seconds)
                else:
                    raise BinaryInstallError(
                        f"Failed to download {binary_name} after {max_retries} attempts: {e}"
                    ) from e

        # Make the binary executable
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
