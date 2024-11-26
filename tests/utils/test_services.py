from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from devservices.utils.services import get_local_services
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


def test_get_local_services_with_invalid_config(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    mock_code_root = tmp_path / "code"
    with (
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(mock_code_root),
        ),
    ):
        os.makedirs(mock_code_root)
        mock_repo_path = mock_code_root / "example"
        create_mock_git_repo("blank_repo", mock_repo_path)
        invalid_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "example-dependency": {"description": "Example dependency"}
                },
                "modes": {},
            }
        }
        create_config_file(mock_repo_path, invalid_config)
        run_git_command(["add", "."], cwd=mock_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=mock_repo_path)

        local_services = get_local_services(str(mock_code_root))
        captured = capsys.readouterr()
        assert not local_services
        assert (
            "example was found with an invalid config: Default mode is required in service config"
            in captured.out
        )
