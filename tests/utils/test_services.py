from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from devservices.exceptions import ServiceNotFoundError
from devservices.utils.services import find_matching_service
from devservices.utils.services import get_local_services
from testing.utils import create_mock_git_repo


def test_get_local_services_with_invalid_config(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    mock_code_root = tmp_path / "code"
    os.makedirs(mock_code_root)
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
        mock_repo_path = mock_code_root / "example"
        create_mock_git_repo("invalid_repo", mock_repo_path)

        local_services = get_local_services(str(mock_code_root))
        captured = capsys.readouterr()
        assert not local_services
        assert (
            "example was found with an invalid config: Error parsing config file:"
            in captured.out
        )


def test_get_local_services_with_valid_config(tmp_path: Path) -> None:
    mock_code_root = tmp_path / "code"
    os.makedirs(mock_code_root)
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
        mock_repo_path = mock_code_root / "basic"
        create_mock_git_repo("basic_repo", mock_repo_path)

        local_services = get_local_services(str(mock_code_root))
        assert len(local_services) == 1
        assert local_services[0].name == "basic"
        assert local_services[0].repo_path == str(mock_repo_path)


def test_get_local_services_skips_non_devservices_repos(tmp_path: Path) -> None:
    mock_code_root = tmp_path / "code"
    os.makedirs(mock_code_root)
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
        mock_basic_repo_path = mock_code_root / "basic"
        mock_non_devservices_repo_path = mock_code_root / "non-devservices"
        create_mock_git_repo("basic_repo", mock_basic_repo_path)
        create_mock_git_repo("non-devservices-repo", mock_non_devservices_repo_path)

        local_services = get_local_services(str(mock_code_root))
        assert len(local_services) == 1
        assert local_services[0].name == "basic"
        assert local_services[0].repo_path == str(mock_basic_repo_path)


def test_find_matching_service_not_found(tmp_path: Path) -> None:
    mock_code_root = tmp_path / "code"
    os.makedirs(mock_code_root)
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
        with pytest.raises(ServiceNotFoundError):
            find_matching_service(str(tmp_path / "non-existent-repo"))
