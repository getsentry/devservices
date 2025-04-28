from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import PROGRAMS_CONF_FILE_NAME

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


def create_programs_conf_file(tmp_path: Path, config: str) -> None:
    devservices_dir = Path(tmp_path, DEVSERVICES_DIR_NAME)
    devservices_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(devservices_dir, PROGRAMS_CONF_FILE_NAME)
    with tmp_file.open("w") as f:
        f.write(config)


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
