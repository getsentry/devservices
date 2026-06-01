from __future__ import annotations

import io
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import yaml

from devservices.constants import DEVSERVICES_DIR_NAME

TESTING_DIR = os.path.abspath(os.path.dirname(__file__))


def get_resource_path(resource_name: str) -> Path:
    return Path(TESTING_DIR, "resources", resource_name)


def create_config_file(
    tmp_path: Path, config: dict[str, object] | dict[str, dict[str, object]]
) -> None:
    devservices_dir = Path(tmp_path, DEVSERVICES_DIR_NAME)
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, "config.yml")
    with tmp_file.open("w") as f:
        yaml.dump(config, f, sort_keys=False, default_flow_style=False)


def run_git_command(command: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *command], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def create_mock_git_repo(test_repo_src: str, path: Path) -> Path:
    resource_path = get_resource_path(test_repo_src)
    shutil.copytree(resource_path, path)
    run_git_command(["-c", "init.defaultBranch=main", "init"], cwd=path)
    run_git_command(["add", "."], cwd=path)
    run_git_command(["commit", "-m", "Initial commit"], cwd=path)
    return path


def make_zip_bytes(
    config: Mapping[str, object] | str | None = None,
    prefix: str = "owner-repo-abc123",
) -> bytes:
    """Build an in-memory GitHub-style zipball with a devservices/config.yml entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if config is not None:
            content = config if isinstance(config, str) else yaml.dump(config)
            zf.writestr(f"{prefix}/devservices/config.yml", content)
    return buf.getvalue()


def make_urlopen_response(zip_bytes: bytes) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.read.return_value = zip_bytes
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def url_dispatch(
    zip_bytes_by_repo_name: dict[str, bytes],
) -> Callable[[mock.MagicMock], mock.MagicMock]:
    """Return a urlopen side_effect that routes requests by repo name in the URL."""

    def _side_effect(request: mock.MagicMock) -> mock.MagicMock:
        url = request.full_url
        for repo_name, zip_bytes in zip_bytes_by_repo_name.items():
            if f"/{repo_name}/" in url:
                return make_urlopen_response(zip_bytes)
        raise AssertionError(f"No mock zip configured for URL: {url}")

    return _side_effect
