from __future__ import annotations

import os
import shutil
import tempfile
from urllib.request import urlopen

from devservices.constants import BINARY_PERMISSIONS
from devservices.constants import DOWNLOAD_TIMEOUT
from devservices.exceptions import BinaryInstallError
from devservices.utils.console import Console
from devservices.utils.retry import retry

DOWNLOAD_ATTEMPTS = 3


def download_file(url: str, path: str) -> None:
    # urlretrieve has no timeout, so a stalled connection would hang forever.
    # The timeout applies to connecting and to each read, not the whole download.
    with urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, open(path, "wb") as f:
        shutil.copyfileobj(response, f)


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
                lambda: download_file(url, temp_file),
                retries=DOWNLOAD_ATTEMPTS,
                delay=1.0,
                backoff=2.0,
                on_retry=lambda e, remaining: console.warning(
                    f"Download failed ({e}). Retrying... ({remaining} retries left)"
                ),
            )
        except Exception as e:
            raise BinaryInstallError(
                f"Failed to download {binary_name} after {DOWNLOAD_ATTEMPTS} attempts: {e}"
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
