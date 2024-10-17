from __future__ import annotations

import os
import shutil
import tempfile
import time
from urllib.request import urlretrieve


def install_binary(
    binary_name: str,
    exec_path: str,
    version: str,
    url: str,
    exception_type: type[Exception],
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = os.path.join(temp_dir, binary_name)

        # Download the binary with retries
        max_retries = 3
        retry_delay_seconds = 1
        print(f"Downloading {binary_name} {version} from {url}...")
        for attempt in range(max_retries):
            try:
                urlretrieve(url, temp_file)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(
                        f"Download failed. Retrying in {retry_delay_seconds} seconds... (Attempt {attempt + 1}/{max_retries - 1})"
                    )
                    time.sleep(retry_delay_seconds)
                else:
                    raise exception_type(
                        f"Failed to download {binary_name} after {max_retries} attempts: {e}"
                    )

        # Make the binary executable
        try:
            os.chmod(temp_file, 0o755)
        except Exception as e:
            raise exception_type(f"Failed to set executable permissions: {e}")

        try:
            shutil.move(temp_file, exec_path)
        except Exception as e:
            raise exception_type(
                f"Failed to move {binary_name} binary to {exec_path}: {e}"
            )
