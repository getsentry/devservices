from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from devservices.configs.service_config import ServiceConfig
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.services import find_matching_service
from devservices.utils.services import get_local_services
from devservices.utils.services import Service
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


@mock.patch(
    "devservices.utils.services.get_local_services",
    return_value=[],
)
def test_find_matching_service_not_found_no_local_services(
    mock_get_local_services: mock.Mock, tmp_path: Path
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
        with pytest.raises(ServiceNotFoundError) as e:
            find_matching_service(str(tmp_path / "non-existent-repo"))

        assert str(e.value) == f"Service '{tmp_path / 'non-existent-repo'}' not found."

        mock_get_local_services.assert_called_once_with(str(mock_code_root))


@mock.patch(
    "devservices.utils.services.get_local_services",
    return_value=[
        Service(
            name="example-service-1",
            repo_path="/path/to/example-service-1",
            config=ServiceConfig(
                version=0.1,
                service_name="example-service-1",
                dependencies={},
                modes={"default": []},
            ),
        ),
        Service(
            name="example-service-2",
            repo_path="/path/to/example-service-2",
            config=ServiceConfig(
                version=0.1,
                service_name="example-service-2",
                dependencies={},
                modes={"default": []},
            ),
        ),
    ],
)
def test_find_matching_service_not_found_with_local_services(
    mock_get_local_services: mock.Mock, tmp_path: Path
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
        with pytest.raises(ServiceNotFoundError) as e:
            find_matching_service(str(tmp_path / "non-existent-repo"))

        assert (
            str(e.value)
            == f"Service '{tmp_path / 'non-existent-repo'}' not found.\nSupported services:\n- example-service-1\n- example-service-2"
        )

        mock_get_local_services.assert_called_once_with(str(mock_code_root))
