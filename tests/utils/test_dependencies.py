from __future__ import annotations

import io
import urllib.error
import zipfile
from collections.abc import Callable
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import pytest
import yaml

from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import DependencyType
from devservices.exceptions import DependencyError
from devservices.exceptions import DependencyNotInstalledError
from devservices.exceptions import InvalidDependencyConfigError
from devservices.exceptions import ModeDoesNotExistError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.dependencies import _fetch_dependency
from devservices.utils.dependencies import _parse_github_repo_path
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import get_installed_remote_dependencies
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import install_dependency
from devservices.utils.dependencies import verify_local_dependencies
from devservices.utils.services import Service
from devservices.utils.services import get_active_service_names
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables

BASIC_SERVICE_CONFIG = {
    "x-sentry-service-config": {
        "version": 0.1,
        "service_name": "basic",
        "dependencies": {},
        "modes": {"default": []},
    }
}

INVALID_SERVICE_CONFIG_YAML = "not_a_service_config: true\n"


def _make_zip_bytes(
    config: Mapping[str, object] | str | None = None,
    prefix: str = "owner-repo-abc123",
) -> bytes:
    """Build an in-memory GitHub-style zipball with only a devservices/ tree."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if config is not None:
            content = config if isinstance(config, str) else yaml.dump(config)
            zf.writestr(f"{prefix}/devservices/config.yml", content)
    return buf.getvalue()


def _make_urlopen_response(zip_bytes: bytes) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.read.return_value = zip_bytes
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _url_dispatch(
    zip_bytes_by_repo_name: dict[str, bytes],
) -> Callable[[mock.MagicMock], mock.MagicMock]:
    """Build a urlopen side_effect that routes requests by repo name in the URL."""

    def _side_effect(request: mock.MagicMock) -> mock.MagicMock:
        url = request.full_url
        for repo_name, zip_bytes in zip_bytes_by_repo_name.items():
            if f"/{repo_name}/" in url:
                return _make_urlopen_response(zip_bytes)
        raise AssertionError(f"No mock zip configured for URL: {url}")

    return _side_effect


def test_parse_github_repo_path_valid() -> None:
    assert (
        _parse_github_repo_path("https://github.com/getsentry/test-repo")
        == "getsentry/test-repo"
    )
    assert (
        _parse_github_repo_path("https://github.com/getsentry/test-repo.git")
        == "getsentry/test-repo"
    )
    assert (
        _parse_github_repo_path("https://github.com/getsentry/test-repo/")
        == "getsentry/test-repo"
    )
    assert _parse_github_repo_path("http://github.com/org/repo") == "org/repo"


def test_parse_github_repo_path_non_github() -> None:
    with pytest.raises(ValueError):
        _parse_github_repo_path("file:///path/to/repo")
    with pytest.raises(ValueError):
        _parse_github_repo_path("invalid-link")
    with pytest.raises(ValueError):
        _parse_github_repo_path("https://gitlab.com/org/repo")


def test_fetch_dependency_success(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="https://github.com/getsentry/test-repo",
    )
    zip_bytes = _make_zip_bytes(BASIC_SERVICE_CONFIG)
    dest = str(tmp_path / "dest")
    with mock.patch(
        "devservices.utils.dependencies.urllib.request.urlopen",
        return_value=_make_urlopen_response(zip_bytes),
    ):
        _fetch_dependency(dep, dest)
    assert (Path(dest) / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME).exists()


def test_fetch_dependency_network_error(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="https://github.com/getsentry/test-repo",
    )
    with (
        mock.patch("devservices.utils.retry.time.sleep"),
        mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        pytest.raises(DependencyError),
    ):
        _fetch_dependency(dep, str(tmp_path / "dest"))


def test_fetch_dependency_bad_zip(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="https://github.com/getsentry/test-repo",
    )
    with mock.patch(
        "devservices.utils.dependencies.urllib.request.urlopen",
        return_value=_make_urlopen_response(b"not a zip"),
    ):
        with pytest.raises(DependencyError):
            _fetch_dependency(dep, str(tmp_path / "dest"))


def test_fetch_dependency_empty_zip(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="https://github.com/getsentry/test-repo",
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with mock.patch(
        "devservices.utils.dependencies.urllib.request.urlopen",
        return_value=_make_urlopen_response(buf.getvalue()),
    ):
        with pytest.raises(DependencyError):
            _fetch_dependency(dep, str(tmp_path / "dest"))


def test_fetch_dependency_no_devservices_dir(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="https://github.com/getsentry/test-repo",
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("owner-repo-abc123/README.md", "hello")
    with mock.patch(
        "devservices.utils.dependencies.urllib.request.urlopen",
        return_value=_make_urlopen_response(buf.getvalue()),
    ):
        with pytest.raises(DependencyError):
            _fetch_dependency(dep, str(tmp_path / "dest"))


def test_fetch_dependency_non_github_url(tmp_path: Path) -> None:
    dep = RemoteConfig(
        repo_name="test-repo",
        branch="main",
        repo_link="file:///path/to/repo",
    )
    with pytest.raises(DependencyError):
        _fetch_dependency(dep, str(tmp_path / "dest"))


def test_verify_local_dependencies_no_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        assert verify_local_dependencies([])


def test_verify_local_dependencies_no_remote_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        dependency = Dependency(
            description="Test dependency",
            dependency_type=DependencyType.COMPOSE,
        )
        assert verify_local_dependencies([dependency])


def test_verify_local_dependencies_with_remote_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        remote_config = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        dependency = Dependency(
            description="Test dependency",
            remote=remote_config,
            dependency_type=DependencyType.COMPOSE,
        )
        assert not verify_local_dependencies([dependency])

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(BASIC_SERVICE_CONFIG)),
        ):
            install_dependency(remote_config)

        assert verify_local_dependencies([dependency])


def test_get_installed_remote_dependencies_empty(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        assert get_installed_remote_dependencies(dependencies=[]) == set()


def test_get_installed_remote_dependencies_single_dep_not_installed(
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = Dependency(
            description="test repo",
            remote=RemoteConfig(
                repo_name="test-repo",
                branch="main",
                repo_link="https://github.com/getsentry/test-repo",
            ),
            dependency_type=DependencyType.SERVICE,
        )
        with pytest.raises(DependencyNotInstalledError):
            get_installed_remote_dependencies(dependencies=[mock_dependency])


def test_get_installed_remote_dependencies_single_dep_installed(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = Dependency(
            description="test repo",
            remote=RemoteConfig(
                repo_name="test-repo",
                branch="main",
                repo_link="https://github.com/getsentry/test-repo",
            ),
            dependency_type=DependencyType.SERVICE,
        )
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(BASIC_SERVICE_CONFIG)),
        ):
            installed_initial = install_dependencies([mock_dependency])
        installed = get_installed_remote_dependencies(dependencies=[mock_dependency])
        assert installed == installed_initial
        assert installed == {
            InstalledRemoteDependency(
                service_name="basic",
                repo_path=str(
                    tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "test-repo"
                ),
            )
        }


def test_install_dependency_invalid_repo(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        remote_config = RemoteConfig(
            repo_name="test-repo", branch="main", repo_link="invalid-link"
        )
        with pytest.raises(DependencyError):
            install_dependency(remote_config)


def test_install_dependency_network_error(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        with (
            mock.patch("devservices.utils.retry.time.sleep"),
            mock.patch(
                "devservices.utils.dependencies.urllib.request.urlopen",
                side_effect=urllib.error.URLError("network unreachable"),
            ),
            pytest.raises(DependencyError),
        ):
            install_dependency(mock_dependency)


def test_install_dependency_basic(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )

        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(BASIC_SERVICE_CONFIG)),
        ):
            install_dependency(mock_dependency)

        # Files outside devservices/ must not be extracted
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / "README.md"
        ).exists()

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


def test_install_dependency_basic_with_update(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        config_v1 = dict(BASIC_SERVICE_CONFIG)
        config_v2 = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "basic",
                "dependencies": {},
                "modes": {"default": []},
                "extra": "added-in-v2",
            }
        }

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=[
                _make_urlopen_response(_make_zip_bytes(config_v1)),
                _make_urlopen_response(_make_zip_bytes(config_v2)),
            ],
        ):
            install_dependency(mock_dependency)
            config_path = (
                tmp_path
                / "dependency-dir"
                / DEPENDENCY_CONFIG_VERSION
                / "test-repo"
                / DEVSERVICES_DIR_NAME
                / CONFIG_FILE_NAME
            )
            assert config_path.exists()
            first_content = config_path.read_text()

            install_dependency(mock_dependency)
            second_content = config_path.read_text()

        assert first_content != second_content
        assert "added-in-v2" in second_content


def test_install_dependency_basic_with_new_file(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        zip_v1 = _make_zip_bytes(BASIC_SERVICE_CONFIG)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "owner-repo-abc123/devservices/config.yml",
                yaml.dump(BASIC_SERVICE_CONFIG),
            )
            zf.writestr("owner-repo-abc123/devservices/extra.yml", "extra: true\n")
        zip_v2 = buf.getvalue()

        dest = (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=[
                _make_urlopen_response(zip_v1),
                _make_urlopen_response(zip_v2),
            ],
        ):
            install_dependency(mock_dependency)
            assert not (dest / "extra.yml").exists()

            install_dependency(mock_dependency)
            assert (dest / CONFIG_FILE_NAME).exists()
            assert (dest / "extra.yml").exists()


def test_install_dependency_basic_with_existing_dir(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )

        # Pre-create the destination with a stale file
        dependency_dir = (
            tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "test-repo"
        )
        dependency_dir.mkdir(parents=True, exist_ok=True)
        (dependency_dir / "existing-file.txt").touch()

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(BASIC_SERVICE_CONFIG)),
        ):
            install_dependency(mock_dependency)

        assert not (dependency_dir / "existing-file.txt").exists()
        assert (dependency_dir / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME).exists()


def test_install_dependency_basic_with_existing_invalid_dir(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )

        dependency_dir = (
            tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "test-repo"
        )
        dependency_dir.mkdir(parents=True, exist_ok=True)
        (dependency_dir / ".git").mkdir()
        (dependency_dir / "existing-file.txt").touch()

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(BASIC_SERVICE_CONFIG)),
        ):
            install_dependency(mock_dependency)

        assert (dependency_dir / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME).exists()


def test_install_dependency_basic_with_overwrite(tmp_path: Path) -> None:
    """A second install overwrites any local edits to the destination."""
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        zip_bytes = _make_zip_bytes(BASIC_SERVICE_CONFIG)
        config_path = (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(zip_bytes),
        ):
            install_dependency(mock_dependency)
            original = config_path.read_text()

            # Tamper with the installed file
            config_path.write_text(original + "\nlocal_edit: true")

            install_dependency(mock_dependency)

        assert config_path.read_text() == original


def test_install_dependency_basic_noop_reinstall(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link="https://github.com/getsentry/test-repo",
        )
        zip_bytes = _make_zip_bytes(BASIC_SERVICE_CONFIG)
        config_path = (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(zip_bytes),
        ):
            install_dependency(mock_dependency)
            assert config_path.exists()
            install_dependency(mock_dependency)
            assert config_path.exists()


def test_install_dependency_nested_dependency(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        main_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "complex",
                "dependencies": {
                    "nested-repo": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "nested-repo",
                            "repo_link": "https://github.com/getsentry/nested-repo",
                            "branch": "main",
                        },
                    }
                },
                "modes": {"default": ["nested-repo"]},
            }
        }
        main_zip = _make_zip_bytes(main_config)
        nested_zip = _make_zip_bytes(BASIC_SERVICE_CONFIG)

        main_repo_dependency = RemoteConfig(
            repo_name="main-repo",
            branch="main",
            repo_link="https://github.com/getsentry/main-repo",
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {"main-repo": main_zip, "nested-repo": nested_zip}
            ),
        ):
            installed = install_dependency(main_repo_dependency)

        assert installed == {
            InstalledRemoteDependency(
                service_name="basic",
                repo_path=str(
                    tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "nested-repo"
                ),
            ),
            InstalledRemoteDependency(
                service_name="complex",
                repo_path=str(
                    tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "main-repo"
                ),
            ),
        }

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "main-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "nested-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


def test_install_dependency_nested_dependency_missing_nested_dependency(
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        main_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "complex",
                "dependencies": {
                    "nested-repo": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "nested-repo",
                            "repo_link": "invalid-link",
                            "branch": "main",
                        },
                    }
                },
                "modes": {"default": ["nested-repo"]},
            }
        }

        main_repo_dependency = RemoteConfig(
            repo_name="main-repo",
            branch="main",
            repo_link="https://github.com/getsentry/main-repo",
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(main_config)),
        ):
            with pytest.raises(DependencyError):
                install_dependency(main_repo_dependency)


def test_install_dependency_does_not_install_unnecessary_dependencies(
    tmp_path: Path,
) -> None:
    """Installing a dependency only pulls in nested deps in the active mode."""
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-b": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-b",
                            "repo_link": "https://github.com/getsentry/repo-b",
                            "branch": "main",
                        },
                    },
                    "unnecessary-repo": {
                        "description": "unnecessary nested dependency",
                        "remote": {
                            "repo_name": "unnecessary-repo",
                            "repo_link": "invalid-link",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-b"], "other": ["unnecessary-repo"]},
            },
        }

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "repo-a": _make_zip_bytes(repo_a_config),
                    "repo-b": _make_zip_bytes(BASIC_SERVICE_CONFIG),
                }
            ),
        ):
            installed = install_dependency(
                RemoteConfig(
                    repo_name="repo-a",
                    branch="main",
                    repo_link="https://github.com/getsentry/repo-a",
                )
            )

        assert installed == {
            InstalledRemoteDependency(
                service_name="repo-a",
                repo_path=str(
                    tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "repo-a"
                ),
            ),
            InstalledRemoteDependency(
                service_name="basic",
                repo_path=str(
                    tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "repo-b"
                ),
            ),
        }


def test_install_dependency_invalid_mode(tmp_path: Path) -> None:
    """Installing with an invalid mode raises ModeDoesNotExistError."""
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-b": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-b",
                            "repo_link": "https://github.com/getsentry/repo-b",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-b"]},
            },
        }

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(_make_zip_bytes(repo_a_config)),
        ):
            with pytest.raises(ModeDoesNotExistError):
                install_dependency(
                    RemoteConfig(
                        repo_name="repo-a",
                        branch="main",
                        repo_link="https://github.com/getsentry/repo-a",
                        mode="invalid-mode",
                    )
                )


def test_install_dependency_invalid_nested_dependency(tmp_path: Path) -> None:
    """Installing a dependency whose nested dep has an invalid config raises InvalidDependencyConfigError."""
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": "https://github.com/getsentry/repo-c",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "repo-a": _make_zip_bytes(repo_a_config),
                    "repo-c": _make_zip_bytes(INVALID_SERVICE_CONFIG_YAML),
                }
            ),
        ):
            with pytest.raises(InvalidDependencyConfigError):
                install_dependency(
                    RemoteConfig(
                        repo_name="repo-a",
                        branch="main",
                        repo_link="https://github.com/getsentry/repo-a",
                    )
                )


def test_install_dependencies_nested_dependency_file_contention(tmp_path: Path) -> None:
    """Concurrent installs of repos sharing a nested dep succeed without corruption."""
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        shared_config = BASIC_SERVICE_CONFIG
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": "https://github.com/getsentry/repo-c",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }
        repo_b_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-b",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": "https://github.com/getsentry/repo-c",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }

        repo_a_dep = Dependency(
            description="repo a",
            remote=RemoteConfig(
                repo_name="repo-a",
                branch="main",
                repo_link="https://github.com/getsentry/repo-a",
            ),
            dependency_type=DependencyType.SERVICE,
        )
        repo_b_dep = Dependency(
            description="repo b",
            remote=RemoteConfig(
                repo_name="repo-b",
                branch="main",
                repo_link="https://github.com/getsentry/repo-b",
            ),
            dependency_type=DependencyType.SERVICE,
        )

        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "repo-a": _make_zip_bytes(repo_a_config),
                    "repo-b": _make_zip_bytes(repo_b_config),
                    "repo-c": _make_zip_bytes(shared_config),
                }
            ),
        ):
            installed = install_dependencies([repo_a_dep, repo_b_dep])

        assert installed == {
            InstalledRemoteDependency(
                service_name="repo-a",
                repo_path=str(
                    tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "repo-a"
                ),
            ),
            InstalledRemoteDependency(
                service_name="repo-b",
                repo_path=str(
                    tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "repo-b"
                ),
            ),
            InstalledRemoteDependency(
                service_name="basic",
                repo_path=str(
                    tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "repo-c"
                ),
            ),
        }

        for repo_name in ("repo-a", "repo-b", "repo-c"):
            assert (
                tmp_path
                / "dependency-dir"
                / DEPENDENCY_CONFIG_VERSION
                / repo_name
                / DEVSERVICES_DIR_NAME
                / CONFIG_FILE_NAME
            ).exists()


@mock.patch(
    "devservices.utils.dependencies.get_active_service_names",
    return_value={"service-1", "service-2"},
)
@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value=set(),
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-3",
        repo_path="/path/to/service-3",
        config=ServiceConfig(
            version=0.1,
            service_name="service-3",
            dependencies={},
            modes={"default": []},
        ),
    ),
)
@pytest.mark.parametrize("exclude_local", [True, False])
def test_get_non_shared_remote_dependencies_no_shared_dependencies(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    mock_get_active_service_names: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that in the case no shared dependencies are present, the list of non-shared remote dependencies
    should be the same, regardless of the exclude_local flag.
    """
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry("service-1", "default", StateTables.STARTED_SERVICES)
        state.update_service_entry("service-2", "default", StateTables.STARTED_SERVICES)
    service_to_stop = Service(
        name="service-1",
        repo_path="/path/to/service-1",
        config=ServiceConfig(
            version=0.1,
            service_name="service-1",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                )
            },
            modes={"default": ["dependency-1"]},
        ),
    )
    non_shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            )
        },
        exclude_local=exclude_local,
    )
    assert len(non_shared_remote_dependencies) == 1
    assert non_shared_remote_dependencies == {
        InstalledRemoteDependency(
            service_name="dependency-1",
            repo_path="/path/to/dependency-1",
            mode="default",
        )
    }


@mock.patch(
    "devservices.utils.dependencies.get_active_service_names",
    return_value={"service-1", "service-2"},
)
@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value={
        InstalledRemoteDependency(
            service_name="dependency-1",
            repo_path="/path/to/dependency-1",
            mode="default",
        )
    },
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-2",
        repo_path="/path/to/service-2",
        config=ServiceConfig(
            version=0.1,
            service_name="service-2",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                )
            },
            modes={"default": ["dependency-1"]},
        ),
    ),
)
@pytest.mark.parametrize("exclude_local", [True, False])
def test_get_non_shared_remote_dependencies_shared_dependencies(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    mock_get_active_service_names: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that when a dependency is shared with another running service,
    it should not be included in the list of non-shared remote dependencies.
    """
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry("service-1", "default", StateTables.STARTED_SERVICES)
        state.update_service_entry("service-2", "default", StateTables.STARTED_SERVICES)
    service_to_stop = Service(
        name="service-1",
        repo_path="/path/to/service-1",
        config=ServiceConfig(
            version=0.1,
            service_name="service-1",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                )
            },
            modes={"default": ["dependency-1"]},
        ),
    )
    non_shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            )
        },
        exclude_local=exclude_local,
    )
    assert len(non_shared_remote_dependencies) == 0
    mock_find_matching_service.assert_called_once_with("service-2")
    mock_get_installed_remote_dependencies.assert_called_once_with(
        [
            Dependency(
                description="dependency-1",
                remote=RemoteConfig(
                    repo_name="dependency-1",
                    repo_link="file://path/to/dependency-1",
                    branch="main",
                ),
                dependency_type=DependencyType.SERVICE,
            )
        ]
    )


# Implies that dependency-3 depends on dependency-1
@mock.patch(
    "devservices.utils.dependencies.get_active_service_names",
    return_value={"service-1", "service-2"},
)
@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value={
        InstalledRemoteDependency(
            service_name="dependency-1",
            repo_path="/path/to/dependency-1",
            mode="default",
        )
    },
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-2",
        repo_path="/path/to/service-2",
        config=ServiceConfig(
            version=0.1,
            service_name="service-2",
            dependencies={
                "dependency-3": Dependency(
                    description="dependency-3",
                    remote=RemoteConfig(
                        repo_name="dependency-3",
                        repo_link="file://path/to/dependency-3",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "dependency-4": Dependency(
                    description="dependency-4",
                    remote=RemoteConfig(
                        repo_name="dependency-4",
                        repo_link="file://path/to/dependency-4",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-3"], "other": ["dependency-4"]},
        ),
    ),
)
@pytest.mark.parametrize("exclude_local", [True, False])
def test_get_non_shared_remote_dependencies_nested_shared_dependencies(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    mock_get_active_service_names: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that when service-2 depends on dependency-3, which in turn depends on dependency-1,
    dependency-1 should be considered shared between service-1 and service-2, while dependency-2
    remains non-shared, regardless of the exclude_local flag since nothing is using a local runtime.
    """
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry("service-1", "default", StateTables.STARTED_SERVICES)
        state.update_service_entry("service-2", "default", StateTables.STARTED_SERVICES)
    service_to_stop = Service(
        name="service-1",
        repo_path="/path/to/service-1",
        config=ServiceConfig(
            version=0.1,
            service_name="service-1",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-1", "dependency-2"]},
        ),
    )
    non_shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            ),
            InstalledRemoteDependency(
                service_name="dependency-2",
                repo_path="/path/to/dependency-2",
                mode="default",
            ),
        },
        exclude_local=exclude_local,
    )
    assert non_shared_remote_dependencies == {
        InstalledRemoteDependency(
            service_name="dependency-2",
            repo_path="/path/to/dependency-2",
            mode="default",
        )
    }
    mock_find_matching_service.assert_called_once_with("service-2")
    # dependency-4 is not in the active mode so it should not be passed to get_installed_remote_dependencies
    mock_get_installed_remote_dependencies.assert_called_once_with(
        [
            Dependency(
                description="dependency-3",
                remote=RemoteConfig(
                    repo_name="dependency-3",
                    repo_link="file://path/to/dependency-3",
                    branch="main",
                ),
                dependency_type=DependencyType.SERVICE,
            )
        ]
    )


@mock.patch(
    "devservices.utils.dependencies.get_active_service_names",
    return_value={"service-1", "service-2"},
)
@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value=set(),
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-2",
        repo_path="/path/to/service-2",
        config=ServiceConfig(
            version=0.1,
            service_name="service-2",
            dependencies={
                "dependency-3": Dependency(
                    description="dependency-3",
                    remote=RemoteConfig(
                        repo_name="dependency-3",
                        repo_link="file://path/to/dependency-3",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-3"]},
        ),
    ),
)
@pytest.mark.parametrize("exclude_local", [True, False])
def test_get_non_shared_remote_dependencies_with_local_runtime_dependency(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    mock_get_active_service_names: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that depending on the exclude_local flag, a service with a local runtime dependency
    should or should not be included in the list of non-shared remote dependencies.
    """
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry("service-1", "default", StateTables.STARTED_SERVICES)
        state.update_service_entry("service-2", "default", StateTables.STARTED_SERVICES)
        state.update_service_runtime("service-2", ServiceRuntime.LOCAL)
    service_to_stop = Service(
        name="service-1",
        repo_path="/path/to/service-1",
        config=ServiceConfig(
            version=0.1,
            service_name="service-1",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "service-2": Dependency(
                    description="service-2",
                    remote=RemoteConfig(
                        repo_name="service-2",
                        repo_link="file://path/to/service-2",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-1", "service-2"]},
        ),
    )
    non_shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            ),
            InstalledRemoteDependency(
                service_name="service-2",
                repo_path="/path/to/service-2",
                mode="default",
            ),
        },
        exclude_local=exclude_local,
    )
    # If exclude_local is True, service-2 is excluded from non-shared deps because it
    # is running with a local runtime and is depended upon by service-1.
    if exclude_local:
        assert non_shared_remote_dependencies == {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            )
        }
    else:
        assert non_shared_remote_dependencies == {
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            ),
            InstalledRemoteDependency(
                service_name="service-2",
                repo_path="/path/to/service-2",
                mode="default",
            ),
        }


@mock.patch("devservices.utils.dependencies.install_dependencies", return_value=[])
def test_install_and_verify_dependencies_simple(
    mock_install_dependencies: mock.Mock, tmp_path: Path
) -> None:
    service = Service(
        name="test-service",
        repo_path="/path/to/test-service",
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-1", "dependency-2"]},
        ),
    )
    install_and_verify_dependencies(service)

    mock_install_dependencies.assert_called_once_with(
        [
            service.config.dependencies["dependency-1"],
            service.config.dependencies["dependency-2"],
        ]
    )


@mock.patch("devservices.utils.dependencies.install_dependencies", return_value=[])
def test_install_and_verify_dependencies_mode_simple(
    mock_install_dependencies: mock.Mock, tmp_path: Path
) -> None:
    service = Service(
        name="test-service",
        repo_path="/path/to/test-service",
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={
                "default": ["dependency-1", "dependency-2"],
                "test": ["dependency-1"],
            },
        ),
    )
    install_and_verify_dependencies(service, modes=["test"])

    mock_install_dependencies.assert_called_once_with(
        [service.config.dependencies["dependency-1"]]
    )


def test_install_and_verify_dependencies_mode_does_not_exist(tmp_path: Path) -> None:
    service = Service(
        name="test-service",
        repo_path="/path/to/test-service",
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="file://path/to/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-1", "dependency-2"]},
        ),
    )
    with pytest.raises(ModeDoesNotExistError):
        install_and_verify_dependencies(service, modes=["unknown-mode"])


def test_construct_dependency_graph_simple(tmp_path: Path) -> None:
    dependency_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "dependency-1",
            "dependencies": {
                "dependency-1": {
                    "description": "dependency-1",
                },
            },
            "modes": {"default": ["dependency-1"]},
        },
        "services": {
            "dependency-1": {
                "image": "dependency-1",
            },
        },
    }
    service = Service(
        name="test-service",
        repo_path="/path/to/test-service",
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={
                "dependency-1": Dependency(
                    description="dependency-1",
                    remote=RemoteConfig(
                        repo_name="dependency-1",
                        repo_link="https://github.com/getsentry/dependency-1",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={"default": ["dependency-1"]},
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            return_value=_make_urlopen_response(
                _make_zip_bytes(dependency_service_config)
            ),
        ):
            install_and_verify_dependencies(service)

        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            DependencyNode(
                name="dependency-1", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="dependency-1", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="dependency-1", dependency_type=DependencyType.COMPOSE
                )
            },
            DependencyNode(
                name="test-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="dependency-1", dependency_type=DependencyType.SERVICE
                )
            },
        }

        assert dependency_graph.get_starting_order() == [
            DependencyNode(name="dependency-1", dependency_type=DependencyType.COMPOSE),
            DependencyNode(name="dependency-1", dependency_type=DependencyType.SERVICE),
            DependencyNode(name="test-service", dependency_type=DependencyType.SERVICE),
        ]


def test_construct_dependency_graph_one_nested_dependency(tmp_path: Path) -> None:
    parent_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": "https://github.com/getsentry/child-service",
                        "branch": "main",
                    },
                },
                "parent-service": {
                    "description": "parent-service",
                },
            },
            "modes": {"default": ["child-service", "parent-service"]},
        },
        "services": {
            "parent-service": {
                "image": "parent-service",
            },
        },
    }
    child_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "child-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                },
            },
            "modes": {"default": ["child-service"]},
        },
        "services": {
            "child-service": {
                "image": "child-service",
            },
        },
    }
    service = Service(
        name="grandparent-service",
        repo_path="/path/to/grandparent-service",
        config=ServiceConfig(
            version=0.1,
            service_name="grandparent-service",
            dependencies={
                "parent-service": Dependency(
                    description="parent-service",
                    remote=RemoteConfig(
                        repo_name="parent-service",
                        repo_link="https://github.com/getsentry/parent-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                    dependency_type=DependencyType.COMPOSE,
                ),
            },
            modes={"default": ["parent-service", "grandparent-service"]},
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "parent-service": _make_zip_bytes(parent_service_config),
                    "child-service": _make_zip_bytes(child_service_config),
                }
            ),
        ):
            install_and_verify_dependencies(service)

        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            DependencyNode(
                name="child-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="child-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.COMPOSE
                )
            },
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="grandparent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.SERVICE
                ),
            },
        }

        starting_order = dependency_graph.get_starting_order()
        assert starting_order.index(
            DependencyNode(name="child-service", dependency_type=DependencyType.SERVICE)
        ) < starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Child service should come before parent service in the starting order"

        assert starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ) < starting_order.index(
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Parent service should come before grandparent service in the starting order"


def test_construct_dependency_graph_shared_dependency(tmp_path: Path) -> None:
    parent_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": "https://github.com/getsentry/child-service",
                        "branch": "main",
                    },
                },
                "parent-service": {
                    "description": "parent-service",
                },
            },
            "modes": {"default": ["child-service", "parent-service"]},
        },
        "services": {
            "parent-service": {
                "image": "parent-service",
            },
        },
    }
    child_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "child-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                },
            },
            "modes": {"default": ["child-service"]},
        },
        "services": {
            "child-service": {
                "image": "child-service",
            },
        },
    }
    service = Service(
        name="grandparent-service",
        repo_path="/path/to/grandparent-service",
        config=ServiceConfig(
            version=0.1,
            service_name="grandparent-service",
            dependencies={
                "parent-service": Dependency(
                    description="parent-service",
                    remote=RemoteConfig(
                        repo_name="parent-service",
                        repo_link="https://github.com/getsentry/parent-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                    dependency_type=DependencyType.COMPOSE,
                ),
                "child-service": Dependency(
                    description="child-service",
                    remote=RemoteConfig(
                        repo_name="child-service",
                        repo_link="https://github.com/getsentry/child-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
            },
            modes={
                "default": ["parent-service", "grandparent-service", "child-service"],
            },
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "parent-service": _make_zip_bytes(parent_service_config),
                    "child-service": _make_zip_bytes(child_service_config),
                }
            ),
        ):
            install_and_verify_dependencies(service)

        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            DependencyNode(
                name="child-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="child-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.COMPOSE
                )
            },
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="grandparent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.SERVICE
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
        }

        starting_order = dependency_graph.get_starting_order()
        assert starting_order.index(
            DependencyNode(name="child-service", dependency_type=DependencyType.SERVICE)
        ) < starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Child service should come before parent service in the starting order"

        assert starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ) < starting_order.index(
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Parent service should come before grandparent service in the starting order"


def test_construct_dependency_graph_non_self_reference(tmp_path: Path) -> None:
    parent_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": "https://github.com/getsentry/child-service",
                        "branch": "main",
                    },
                },
                "parent-service-container": {
                    "description": "parent-service-container",
                },
            },
            "modes": {"default": ["child-service", "parent-service-container"]},
        },
        "services": {
            "parent-service-container": {
                "image": "parent-service-container",
            },
        },
    }
    child_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "child-service",
            "dependencies": {
                "child-service-container": {
                    "description": "child-service-container",
                },
            },
            "modes": {"default": ["child-service-container"]},
        },
        "services": {
            "child-service-container": {
                "image": "child-service-container",
            },
        },
    }
    service = Service(
        name="grandparent-service",
        repo_path="/path/to/grandparent-service",
        config=ServiceConfig(
            version=0.1,
            service_name="grandparent-service",
            dependencies={
                "parent-service": Dependency(
                    description="parent-service",
                    remote=RemoteConfig(
                        repo_name="parent-service",
                        repo_link="https://github.com/getsentry/parent-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "grandparent-service-container": Dependency(
                    description="grandparent-service-container",
                    dependency_type=DependencyType.COMPOSE,
                ),
            },
            modes={"default": ["parent-service", "grandparent-service-container"]},
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "parent-service": _make_zip_bytes(parent_service_config),
                    "child-service": _make_zip_bytes(child_service_config),
                }
            ),
        ):
            install_and_verify_dependencies(service)

        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            DependencyNode(
                name="child-service-container", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="child-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="child-service-container",
                    dependency_type=DependencyType.COMPOSE,
                )
            },
            DependencyNode(
                name="parent-service-container", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="parent-service-container",
                    dependency_type=DependencyType.COMPOSE,
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
            DependencyNode(
                name="grandparent-service-container",
                dependency_type=DependencyType.COMPOSE,
            ): set(),
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="grandparent-service-container",
                    dependency_type=DependencyType.COMPOSE,
                ),
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.SERVICE
                ),
            },
        }

        starting_order = dependency_graph.get_starting_order()
        assert starting_order.index(
            DependencyNode(name="child-service", dependency_type=DependencyType.SERVICE)
        ) < starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Child service should come before parent service in the starting order"

        assert starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ) < starting_order.index(
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Parent service should come before grandparent service in the starting order"


def test_construct_dependency_graph_complex(tmp_path: Path) -> None:
    parent_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": "https://github.com/getsentry/child-service",
                        "branch": "main",
                    },
                },
                "parent-service": {
                    "description": "parent-service",
                },
                "other-service": {
                    "description": "other-service",
                    "remote": {
                        "repo_name": "other-service",
                        "repo_link": "file://does-not-exist",
                        "branch": "main",
                    },
                },
            },
            "modes": {
                "default": ["child-service", "parent-service"],
                "other": ["other-service"],
            },
        },
        "services": {
            "parent-service": {
                "image": "parent-service",
            },
        },
    }
    child_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "child-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                },
                "other-service": {
                    "description": "other-service",
                    "remote": {
                        "repo_name": "other-service",
                        "repo_link": "file://does-not-exist",
                        "branch": "main",
                    },
                },
            },
            "modes": {"default": ["child-service"], "other": ["other-service"]},
        },
        "services": {
            "child-service": {
                "image": "child-service",
            },
        },
    }
    grandparent_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "grandparent-service",
            "dependencies": {
                "parent-service": {
                    "description": "parent-service",
                    "remote": {
                        "repo_name": "parent-service",
                        "repo_link": "https://github.com/getsentry/parent-service",
                        "branch": "main",
                    },
                },
                "other-service": {
                    "description": "other-service",
                    "remote": {
                        "repo_name": "other-service",
                        "repo_link": "file://does-not-exist",
                        "branch": "main",
                    },
                },
                "grandparent-service": {
                    "description": "grandparent-service",
                },
            },
            "modes": {
                "default": ["parent-service", "grandparent-service"],
                "other": ["other-service"],
            },
        },
        "services": {
            "grandparent-service": {
                "image": "grandparent-service",
            },
        },
    }
    service = Service(
        name="complex-service",
        repo_path="/path/to/complex-service",
        config=ServiceConfig(
            version=0.1,
            service_name="complex-service",
            dependencies={
                "child-service": Dependency(
                    description="child-service",
                    remote=RemoteConfig(
                        repo_name="child-service",
                        repo_link="https://github.com/getsentry/child-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                    remote=RemoteConfig(
                        repo_name="grandparent-service",
                        repo_link="https://github.com/getsentry/grandparent-service",
                        branch="main",
                    ),
                    dependency_type=DependencyType.SERVICE,
                ),
                "complex-service": Dependency(
                    description="complex-service",
                    dependency_type=DependencyType.COMPOSE,
                ),
            },
            modes={
                "default": ["grandparent-service", "child-service", "complex-service"],
            },
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        with mock.patch(
            "devservices.utils.dependencies.urllib.request.urlopen",
            side_effect=_url_dispatch(
                {
                    "parent-service": _make_zip_bytes(parent_service_config),
                    "child-service": _make_zip_bytes(child_service_config),
                    "grandparent-service": _make_zip_bytes(grandparent_service_config),
                }
            ),
        ):
            install_and_verify_dependencies(service)

        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            DependencyNode(
                name="child-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="child-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.COMPOSE
                )
            },
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="grandparent-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="parent-service", dependency_type=DependencyType.SERVICE
                ),
            },
            DependencyNode(
                name="complex-service", dependency_type=DependencyType.COMPOSE
            ): set(),
            DependencyNode(
                name="complex-service", dependency_type=DependencyType.SERVICE
            ): {
                DependencyNode(
                    name="complex-service", dependency_type=DependencyType.COMPOSE
                ),
                DependencyNode(
                    name="grandparent-service", dependency_type=DependencyType.SERVICE
                ),
                DependencyNode(
                    name="child-service", dependency_type=DependencyType.SERVICE
                ),
            },
        }

        starting_order = dependency_graph.get_starting_order()
        assert starting_order.index(
            DependencyNode(name="child-service", dependency_type=DependencyType.SERVICE)
        ) < starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Child service should come before parent service in the starting order"

        assert starting_order.index(
            DependencyNode(
                name="parent-service", dependency_type=DependencyType.SERVICE
            )
        ) < starting_order.index(
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            )
        ), "Parent service should come before grandparent service in the starting order"

        assert starting_order.index(
            DependencyNode(
                name="complex-service", dependency_type=DependencyType.SERVICE
            )
        ) > starting_order.index(
            DependencyNode(
                name="grandparent-service", dependency_type=DependencyType.SERVICE
            )
        ), (
            "Grandparent service should come before complex service in the starting order"
        )


@mock.patch(
    "devservices.utils.services.find_matching_service",
    side_effect=ServiceNotFoundError("Service 'stale-service' not found."),
)
def test_get_active_service_names_removes_stale_entries(
    mock_find_matching_service: mock.Mock,
    tmp_path: Path,
) -> None:
    """
    Test that get_active_service_names(clean_stale_entries=True) removes stale entries
    from the state DB and excludes them from the result.
    """
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry("service-1", "default", StateTables.STARTED_SERVICES)
        state.update_service_entry(
            "stale-service", "default", StateTables.STARTED_SERVICES
        )
        # Should NOT raise ServiceNotFoundError
        active_services = get_active_service_names(clean_stale_entries=True)
        # Both entries are stale (mock raises for all), so none remain
        assert len(active_services) == 0
        # Verify the stale entries were removed from the state DB
        remaining = state.get_service_entries(StateTables.STARTED_SERVICES)
        assert "stale-service" not in remaining
        assert "service-1" not in remaining
