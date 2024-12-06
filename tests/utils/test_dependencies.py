from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DependencyError
from devservices.exceptions import DependencyNotInstalledError
from devservices.exceptions import FailedToSetGitConfigError
from devservices.exceptions import InvalidDependencyConfigError
from devservices.exceptions import ModeDoesNotExistError
from devservices.utils.dependencies import construct_dependency_graph
from devservices.utils.dependencies import get_installed_remote_dependencies
from devservices.utils.dependencies import get_non_shared_remote_dependencies
from devservices.utils.dependencies import GitConfigManager
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import install_dependencies
from devservices.utils.dependencies import install_dependency
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.dependencies import verify_local_dependencies
from devservices.utils.services import Service
from devservices.utils.state import State
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


@mock.patch("devservices.utils.dependencies.subprocess.run")
def test_git_config_manager_ensure_config_failure(
    mock_run: mock.Mock, tmp_path: Path
) -> None:
    repo_dir = tmp_path / "test-repo"
    create_mock_git_repo("basic_repo", repo_dir)
    mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd="test")
    git_config_manager = GitConfigManager(
        str(repo_dir),
        {
            "test.config": "test-value",
        },
    )
    with pytest.raises(FailedToSetGitConfigError):
        git_config_manager.ensure_config()


def test_git_config_manager_ensure_config_simple_repo(tmp_path: Path) -> None:
    repo_dir = tmp_path / "test-repo"
    create_mock_git_repo("basic_repo", repo_dir)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(["git", "config", "--get", "test.config"], cwd=repo_dir)
    git_config_manager = GitConfigManager(
        str(repo_dir),
        {
            "test.config": "test-value",
        },
    )
    git_config_manager.ensure_config()
    assert (
        subprocess.check_output(["git", "config", "--get", "test.config"], cwd=repo_dir)
        .decode()
        .strip()
        == "test-value"
    )


def test_git_config_manager_ensure_config_sparse_checkout(tmp_path: Path) -> None:
    repo_dir = tmp_path / "test-repo"
    create_mock_git_repo("basic_repo", repo_dir)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(["git", "sparse-checkout", "list"], cwd=repo_dir)
    git_config_manager = GitConfigManager(
        str(repo_dir),
        {
            "test.config": "test-value",
        },
        sparse_pattern="test-pattern",
    )
    git_config_manager.ensure_config()
    assert (
        subprocess.check_output(["git", "sparse-checkout", "list"], cwd=repo_dir)
        .decode()
        .strip()
        == "test-pattern"
    )


def test_git_config_manager_ensure_config_sparse_checkout_overwrite(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "test-repo"
    create_mock_git_repo("basic_repo", repo_dir)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.check_output(["git", "sparse-checkout", "list"], cwd=repo_dir)
    git_config_manager = GitConfigManager(
        str(repo_dir),
        {
            "test.config": "test-value",
        },
        sparse_pattern="test-pattern",
    )
    git_config_manager.ensure_config()
    assert (
        subprocess.check_output(["git", "sparse-checkout", "list"], cwd=repo_dir)
        .decode()
        .strip()
        == "test-pattern"
    )

    # Overwrite the sparse checkout pattern and ensure it is set correctly
    git_config_manager = GitConfigManager(
        str(repo_dir),
        {
            "test.config": "test-value",
        },
        sparse_pattern="new-pattern",
    )

    git_config_manager.ensure_config()

    assert (
        subprocess.check_output(["git", "sparse-checkout", "list"], cwd=repo_dir)
        .decode()
        .strip()
        == "new-pattern"
    )


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
        )
        assert verify_local_dependencies([dependency])


def test_verify_local_dependencies_with_remote_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        remote_config = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )
        dependency = Dependency(
            description="Test dependency",
            remote=remote_config,
        )
        assert not verify_local_dependencies([dependency])

        install_dependency(remote_config)

        assert verify_local_dependencies([dependency])


def test_get_installed_remote_dependencies_empty(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        installed_remote_dependencies = get_installed_remote_dependencies(
            dependencies=[]
        )
        assert installed_remote_dependencies == set()


def test_get_installed_remote_dependencies_single_dep_not_installed(
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = Dependency(
            description="test repo",
            remote=RemoteConfig(
                repo_name="test-repo",
                branch="main",
                repo_link=f"file://{tmp_path / 'test-repo'}",
            ),
        )
        with pytest.raises(DependencyNotInstalledError):
            get_installed_remote_dependencies(dependencies=[mock_dependency])


def test_get_installed_remote_dependencies_single_dep_installed(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = Dependency(
            description="test repo",
            remote=RemoteConfig(
                repo_name="test-repo",
                branch="main",
                repo_link=f"file://{tmp_path / 'test-repo'}",
            ),
        )
        installed_remote_dependencies_initial = install_dependencies([mock_dependency])
        installed_remote_dependencies = get_installed_remote_dependencies(
            dependencies=[mock_dependency]
        )
        assert installed_remote_dependencies == installed_remote_dependencies_initial
        assert installed_remote_dependencies == set(
            [
                InstalledRemoteDependency(
                    service_name="basic",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "test-repo"
                    ),
                )
            ]
        )


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


@mock.patch("devservices.utils.dependencies.GitConfigManager.ensure_config")
def test_install_dependency_git_config_failure(
    ensure_config_mock: mock.Mock, tmp_path: Path
) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )
        ensure_config_mock.side_effect = FailedToSetGitConfigError()

        with pytest.raises(DependencyError) as e:
            install_dependency(mock_dependency)

        assert e.value.repo_name == "test-repo"
        assert e.value.repo_link == f"file://{tmp_path / 'test-repo'}"
        assert e.value.branch == "main"

        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


def test_install_dependency_basic(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Sanity check that the config file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        install_dependency(mock_dependency)

        # Make sure that files outside of the devservices directory are not copied
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

        # Check that the git config options are set correctly
        for (
            git_config_option_key,
            git_config_option_value,
        ) in DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS.items():
            assert (
                subprocess.check_output(
                    ["git", "config", "--get", git_config_option_key],
                    cwd=tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "test-repo",
                )
                .decode()
                .strip()
                == git_config_option_value
            )


def test_install_dependency_basic_with_edit(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_git_repo = create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Sanity check that the config file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        install_dependency(mock_dependency)

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Append a new line to the config file in the mock repo and commit the change
        with open(
            mock_git_repo / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME, mode="a"
        ) as f:
            f.write("\nedited: true")

        run_git_command(["add", "."], cwd=mock_git_repo)
        run_git_command(["commit", "-m", "Edit config file"], cwd=mock_git_repo)

        install_dependency(mock_dependency)

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Check that the config file in the dependency directory has the new line appended
        with open(
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME,
            mode="r",
        ) as f:
            assert f.read().endswith("\nedited: true")


def test_install_dependency_basic_with_new_tracked_file(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_git_repo = create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Sanity check that the config file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        install_dependency(mock_dependency)

        # Sanity check that the new file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / "new-file.txt"
        ).exists()

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Add a new file to the mock repo and commit the change
        with open(mock_git_repo / DEVSERVICES_DIR_NAME / "new-file.txt", mode="w") as f:
            f.write("New test file")
        run_git_command(["add", "."], cwd=mock_git_repo)
        run_git_command(["commit", "-m", "Add new file"], cwd=mock_git_repo)

        install_dependency(mock_dependency)

        # Sanity check that the existing config file is still there
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Check that the new file is now in the dependency directory
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / "new-file.txt"
        ).exists()


def test_install_dependency_basic_with_existing_dir(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Create the dependency directory and populate it
        dependency_dir = (
            tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "test-repo"
        )
        dependency_dir.mkdir(parents=True, exist_ok=True)
        (dependency_dir / "existing-file.txt").touch()

        install_dependency(mock_dependency)

        # Make sure that files outside of the devservices directory are not copied
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


def test_install_dependency_basic_with_existing_invalid_repo(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Create the dependency directory and populate it
        dependency_dir = (
            tmp_path / "dependency-dir" / DEPENDENCY_CONFIG_VERSION / "test-repo"
        )
        dependency_dir.mkdir(parents=True, exist_ok=True)
        dependency_git_dir = dependency_dir / ".git"
        dependency_git_dir.mkdir(parents=True, exist_ok=True)
        (dependency_dir / "existing-file.txt").touch()

        install_dependency(mock_dependency)

        # Make sure that files outside of the devservices directory are not copied
        assert not (tmp_path / "dependency-dir" / "test-repo" / "README.md").exists()

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


def test_install_dependency_basic_with_existing_repo_conflicts(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_git_repo = create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        install_dependency(mock_dependency)

        # Make sure that files outside of the devservices directory are not copied
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

        # Append a new line to the config file in the mock repo and commit the change
        with open(
            mock_git_repo / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME, mode="a"
        ) as f:
            f.write("\nedited: true")

        run_git_command(["add", "."], cwd=mock_git_repo)
        run_git_command(["commit", "-m", "Edit config file"], cwd=mock_git_repo)

        # Edit the working copy and leave changes unstaged
        with open(
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME,
            mode="a",
        ) as f:
            f.write("\nConflict")

        install_dependency(mock_dependency)

        # Check that the config file in the dependency directory has the new line appended
        with open(
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME,
            mode="r",
        ) as f:
            assert f.read().endswith("\nedited: true")


def test_install_dependency_basic_with_corrupted_repo(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        mock_git_repo = create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Sanity check that the config file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        install_dependency(mock_dependency)

        # Sanity check that the new file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / "new-file.txt"
        ).exists()

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Corrupt the git repository by deleting the .git directory
        shutil.rmtree(mock_git_repo / ".git")

        with pytest.raises(DependencyError):
            install_dependency(mock_dependency)


def test_install_dependency_basic_with_noop_update(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        # Sanity check that the config file is not in the dependency directory (yet)
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        install_dependency(mock_dependency)

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        # Check if the local repo is up-to-date
        install_dependency(mock_dependency)

        # Sanity check that the existing config file is still there
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "test-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


def test_install_dependency_basic_git_config_self_fix(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        create_mock_git_repo("basic_repo", tmp_path / "test-repo")
        mock_dependency = RemoteConfig(
            repo_name="test-repo",
            branch="main",
            repo_link=f"file://{tmp_path / 'test-repo'}",
        )

        install_dependency(mock_dependency)

        # Check that the git config options are set correctly
        for (
            git_config_option_key,
            git_config_option_value,
        ) in DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS.items():
            assert (
                subprocess.check_output(
                    ["git", "config", "--get", git_config_option_key],
                    cwd=tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "test-repo",
                )
                .decode()
                .strip()
                == git_config_option_value
            )

        # Mess up the git config by setting the wrong values
        for (
            git_config_option_key,
            git_config_option_value,
        ) in DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS.items():
            run_git_command(
                ["config", git_config_option_key, "wrong-value"],
                cwd=tmp_path
                / "dependency-dir"
                / DEPENDENCY_CONFIG_VERSION
                / "test-repo",
            )

        for (
            git_config_option_key,
            git_config_option_value,
        ) in DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS.items():
            assert (
                subprocess.check_output(
                    ["git", "config", "--get", git_config_option_key],
                    cwd=tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "test-repo",
                )
                .decode()
                .strip()
                != git_config_option_value
            )

        install_dependency(mock_dependency)

        # Check that the git config options are set correctly
        for (
            git_config_option_key,
            git_config_option_value,
        ) in DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS.items():
            assert (
                subprocess.check_output(
                    ["git", "config", "--get", git_config_option_key],
                    cwd=tmp_path
                    / "dependency-dir"
                    / DEPENDENCY_CONFIG_VERSION
                    / "test-repo",
                )
                .decode()
                .strip()
                == git_config_option_value
            )


def test_install_dependency_nested_dependency(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        nested_repo_path = create_mock_git_repo("basic_repo", tmp_path / "nested-repo")
        main_repo_path = create_mock_git_repo("blank_repo", tmp_path / "main-repo")
        mock_git_repo_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "complex",
                "dependencies": {
                    "nested-repo": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "nested-repo",
                            "repo_link": f"file://{nested_repo_path}",
                            "branch": "main",
                        },
                    }
                },
                "modes": {"default": ["nested-repo"]},
            }
        }
        create_config_file(main_repo_path, mock_git_repo_config)
        run_git_command(["add", "."], cwd=main_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=main_repo_path)

        main_repo_dependency = RemoteConfig(
            repo_name="main-repo",
            branch="main",
            repo_link=f"file://{main_repo_path}",
        )

        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "main-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "nested-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        installed_remote_dependencies = install_dependency(main_repo_dependency)

        assert installed_remote_dependencies == set(
            [
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
            ]
        )

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
        main_repo_path = create_mock_git_repo("blank_repo", tmp_path / "main-repo")
        mock_git_repo_config = {
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
        create_config_file(main_repo_path, mock_git_repo_config)
        run_git_command(["add", "."], cwd=main_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=main_repo_path)

        main_repo_dependency = RemoteConfig(
            repo_name="main-repo",
            branch="main",
            repo_link=f"file://{main_repo_path}",
        )

        with pytest.raises(DependencyError):
            install_dependency(main_repo_dependency)


def test_install_dependency_nested_dependency_with_edits(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        nested_repo_path = create_mock_git_repo("basic_repo", tmp_path / "nested-repo")
        main_repo_path = create_mock_git_repo("blank_repo", tmp_path / "main-repo")
        mock_git_repo_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "complex",
                "dependencies": {
                    "nested-repo": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "nested-repo",
                            "repo_link": f"file://{nested_repo_path}",
                            "branch": "main",
                        },
                    }
                },
                "modes": {"default": ["nested-repo"]},
            }
        }
        create_config_file(main_repo_path, mock_git_repo_config)
        run_git_command(["add", "."], cwd=main_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=main_repo_path)

        main_repo_dependency = RemoteConfig(
            repo_name="main-repo",
            branch="main",
            repo_link=f"file://{main_repo_path}",
        )

        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "main-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()
        assert not (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "nested-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()

        installed_remote_dependencies = install_dependency(main_repo_dependency)

        assert installed_remote_dependencies == set(
            [
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
            ]
        )

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

        with open(
            main_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME, mode="a"
        ) as f:
            f.write("\nedited: true")

        run_git_command(["add", "."], cwd=main_repo_path)
        run_git_command(["commit", "-m", "Edit config file"], cwd=main_repo_path)

        with open(
            nested_repo_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME, mode="a"
        ) as f:
            f.write("\nedited: true")

        run_git_command(["add", "."], cwd=nested_repo_path)
        run_git_command(["commit", "-m", "Edit config file"], cwd=nested_repo_path)

        install_dependency(main_repo_dependency)

        with open(
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "main-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME,
            mode="r",
        ) as f:
            assert f.read().endswith("\nedited: true")

        with open(
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "nested-repo"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME,
            mode="r",
        ) as f:
            assert f.read().endswith("\nedited: true")


def test_install_dependency_does_not_install_unnecessary_dependencies(
    tmp_path: Path,
) -> None:
    """
    Test that installing a dependency does not install nested dependencies not in the modes.
    """
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_path = create_mock_git_repo("blank_repo", tmp_path / "repo-a")
        repo_b_path = create_mock_git_repo("basic_repo", tmp_path / "repo-b")
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-b": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-b",
                            "repo_link": f"file://{repo_b_path}",
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
        create_config_file(repo_a_path, repo_a_config)
        run_git_command(["add", "."], cwd=repo_a_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=repo_a_path)

        repo_a_dependency = RemoteConfig(
            repo_name="repo-a",
            branch="main",
            repo_link=f"file://{repo_a_path}",
        )

        installed_remote_dependencies = install_dependency(repo_a_dependency)

        assert installed_remote_dependencies == set(
            [
                InstalledRemoteDependency(
                    service_name="repo-a",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "repo-a"
                    ),
                ),
                InstalledRemoteDependency(
                    service_name="basic",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "repo-b"
                    ),
                ),
            ]
        )


def test_install_dependency_invalid_mode(
    tmp_path: Path,
) -> None:
    """
    Test that installing a dependency with an invalid mode raises an error.
    """
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_path = create_mock_git_repo("blank_repo", tmp_path / "repo-a")
        repo_b_path = create_mock_git_repo("basic_repo", tmp_path / "repo-b")
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-b": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-b",
                            "repo_link": f"file://{repo_b_path}",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-b"]},
            },
        }
        create_config_file(repo_a_path, repo_a_config)
        run_git_command(["add", "."], cwd=repo_a_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=repo_a_path)

        repo_a_dependency = RemoteConfig(
            repo_name="repo-a",
            branch="main",
            repo_link=f"file://{repo_a_path}",
            mode="invalid-mode",
        )

        with pytest.raises(ModeDoesNotExistError):
            install_dependency(repo_a_dependency)


def test_install_dependency_invalid_nested_dependency(tmp_path: Path) -> None:
    """
    Test that installing a nested dependency with an invalid config raises an error.
    """
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_path = create_mock_git_repo("blank_repo", tmp_path / "repo-a")
        repo_c_path = create_mock_git_repo("invalid_repo", tmp_path / "repo-c")
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": f"file://{repo_c_path}",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }
        create_config_file(repo_a_path, repo_a_config)
        run_git_command(["add", "."], cwd=repo_a_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=repo_a_path)

        repo_a_dependency = RemoteConfig(
            repo_name="repo-a",
            branch="main",
            repo_link=f"file://{repo_a_path}",
        )

        with pytest.raises(InvalidDependencyConfigError):
            install_dependency(repo_a_dependency)


def test_install_dependencies_nested_dependency_file_contention(tmp_path: Path) -> None:
    """
    Test that installing multiple dependencies that share a nested dependency
    does not cause file contention issues.
    """
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        repo_a_path = create_mock_git_repo("blank_repo", tmp_path / "repo-a")
        repo_b_path = create_mock_git_repo("blank_repo", tmp_path / "repo-b")
        repo_c_path = create_mock_git_repo("basic_repo", tmp_path / "repo-c")
        repo_a_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-a",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": f"file://{repo_c_path}",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }
        create_config_file(repo_a_path, repo_a_config)
        run_git_command(["add", "."], cwd=repo_a_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=repo_a_path)

        repo_b_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "repo-b",
                "dependencies": {
                    "repo-c": {
                        "description": "nested dependency",
                        "remote": {
                            "repo_name": "repo-c",
                            "repo_link": f"file://{repo_c_path}",
                            "branch": "main",
                        },
                    },
                },
                "modes": {"default": ["repo-c"]},
            }
        }
        create_config_file(repo_b_path, repo_b_config)
        run_git_command(["add", "."], cwd=repo_b_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=repo_b_path)

        repo_a_dependency = Dependency(
            description="repo a",
            remote=RemoteConfig(
                repo_name="repo-a",
                branch="main",
                repo_link=f"file://{repo_a_path}",
            ),
        )
        repo_b_dependency = Dependency(
            description="repo b",
            remote=RemoteConfig(
                repo_name="repo-b",
                branch="main",
                repo_link=f"file://{repo_b_path}",
            ),
        )
        dependencies = [repo_a_dependency, repo_b_dependency]

        installed_remote_dependencies = install_dependencies(dependencies)

        assert installed_remote_dependencies == set(
            [
                InstalledRemoteDependency(
                    service_name="repo-a",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "repo-a"
                    ),
                ),
                InstalledRemoteDependency(
                    service_name="repo-b",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "repo-b"
                    ),
                ),
                InstalledRemoteDependency(
                    service_name="basic",
                    repo_path=str(
                        tmp_path
                        / "dependency-dir"
                        / DEPENDENCY_CONFIG_VERSION
                        / "repo-c"
                    ),
                ),
            ]
        )

        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "repo-a"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "repo-b"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()
        assert (
            tmp_path
            / "dependency-dir"
            / DEPENDENCY_CONFIG_VERSION
            / "repo-c"
            / DEVSERVICES_DIR_NAME
            / CONFIG_FILE_NAME
        ).exists()


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
def test_get_non_shared_remote_dependencies_no_shared_dependencies(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("service-1", "default")
        state.update_started_service("service-2", "default")
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
                )
            },
            modes={"default": ["dependency-1"]},
        ),
    )
    shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        set(
            [
                InstalledRemoteDependency(
                    service_name="dependency-1",
                    repo_path="/path/to/dependency-1",
                    mode="default",
                )
            ]
        ),
    )
    assert len(shared_remote_dependencies) == 1
    assert shared_remote_dependencies == {
        InstalledRemoteDependency(
            service_name="dependency-1",
            repo_path="/path/to/dependency-1",
            mode="default",
        )
    }


@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value=set(
        [
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            )
        ]
    ),
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-2",
        repo_path="/path/to/service-2",
        config=ServiceConfig(
            version=0.1,
            service_name="service-2",
            dependencies={},
            modes={"default": []},
        ),
    ),
)
def test_get_non_shared_remote_dependencies_shared_dependencies(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("service-1", "default")
        state.update_started_service("service-2", "default")
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
                )
            },
            modes={"default": ["dependency-1"]},
        ),
    )
    shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        set(
            [
                InstalledRemoteDependency(
                    service_name="dependency-1",
                    repo_path="/path/to/dependency-1",
                    mode="default",
                )
            ]
        ),
    )
    assert len(shared_remote_dependencies) == 0


@mock.patch(
    "devservices.utils.dependencies.get_installed_remote_dependencies",
    return_value=set(
        [
            InstalledRemoteDependency(
                service_name="dependency-1",
                repo_path="/path/to/dependency-1",
                mode="default",
            )
        ]
    ),
)
@mock.patch(
    "devservices.utils.dependencies.find_matching_service",
    return_value=Service(
        name="service-1",
        repo_path="/path/to/service-2",
        config=ServiceConfig(
            version=0.1,
            service_name="service-2",
            dependencies={},
            modes={"default": []},
        ),
    ),
)
def test_get_non_shared_remote_dependencies_complex(
    mock_find_matching_service: mock.Mock,
    mock_get_installed_remote_dependencies: mock.Mock,
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("service-1", "default")
        state.update_started_service("service-2", "default")
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
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                ),
            },
            modes={"default": ["dependency-1", "dependency-2"]},
        ),
    )
    shared_remote_dependencies = get_non_shared_remote_dependencies(
        service_to_stop,
        set(
            [
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
            ]
        ),
    )
    assert len(shared_remote_dependencies) == 1
    assert shared_remote_dependencies == {
        InstalledRemoteDependency(
            service_name="dependency-2",
            repo_path="/path/to/dependency-2",
            mode="default",
        )
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
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
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
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
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
                ),
                "dependency-2": Dependency(
                    description="dependency-2",
                    remote=RemoteConfig(
                        repo_name="dependency-2",
                        repo_link="file://path/to/dependency-2",
                        branch="main",
                    ),
                ),
            },
            modes={"default": ["dependency-1", "dependency-2"]},
        ),
    )
    with pytest.raises(ModeDoesNotExistError):
        install_and_verify_dependencies(service, modes=["unknown-mode"])


def test_construct_dependency_graph_simple(
    tmp_path: Path,
) -> None:
    dependency_service_repo_path = tmp_path / "dependency-service-repo"
    create_mock_git_repo("blank_repo", dependency_service_repo_path)
    dependency_service_repo_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "test-service",
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
    create_config_file(dependency_service_repo_path, dependency_service_repo_config)
    run_git_command(["add", "."], cwd=dependency_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=dependency_service_repo_path
    )
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
                        repo_link=f"file://{dependency_service_repo_path}",
                        branch="main",
                    ),
                ),
            },
            modes={
                "default": ["dependency-1"],
            },
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        install_and_verify_dependencies(service)
        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            "dependency-1": set(),
            "test-service": {"dependency-1"},
        }

        assert dependency_graph.get_starting_order() == ["dependency-1", "test-service"]


def test_construct_dependency_graph_one_nested_dependency(
    tmp_path: Path,
) -> None:
    parent_service_repo_path = tmp_path / "parent-service-repo"
    child_service_repo_path = tmp_path / "child-service-repo"
    create_mock_git_repo("blank_repo", parent_service_repo_path)
    create_mock_git_repo("blank_repo", child_service_repo_path)
    parent_service_repo_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": f"file://{child_service_repo_path}",
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
    child_service_repo_config = {
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
    create_config_file(parent_service_repo_path, parent_service_repo_config)
    create_config_file(child_service_repo_path, child_service_repo_config)
    run_git_command(["add", "."], cwd=parent_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=parent_service_repo_path
    )
    run_git_command(["add", "."], cwd=child_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=child_service_repo_path
    )
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
                        repo_link=f"file://{parent_service_repo_path}",
                        branch="main",
                    ),
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                ),
            },
            modes={
                "default": ["parent-service", "grandparent-service"],
            },
        ),
    )

    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        install_and_verify_dependencies(service)
        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            "child-service": set(),
            "parent-service": {"child-service"},
            "grandparent-service": {"parent-service"},
        }

        assert dependency_graph.get_starting_order() == [
            "child-service",
            "parent-service",
            "grandparent-service",
        ]


def test_construct_dependency_graph_shared_dependency(
    tmp_path: Path,
) -> None:
    parent_service_repo_path = tmp_path / "parent-service-repo"
    child_service_repo_path = tmp_path / "child-service-repo"
    create_mock_git_repo("blank_repo", parent_service_repo_path)
    create_mock_git_repo("blank_repo", child_service_repo_path)
    parent_service_repo_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": f"file://{child_service_repo_path}",
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
    child_service_repo_config = {
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
    create_config_file(parent_service_repo_path, parent_service_repo_config)
    create_config_file(child_service_repo_path, child_service_repo_config)
    run_git_command(["add", "."], cwd=parent_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=parent_service_repo_path
    )
    run_git_command(["add", "."], cwd=child_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=child_service_repo_path
    )
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
                        repo_link=f"file://{parent_service_repo_path}",
                        branch="main",
                    ),
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                ),
                "child-service": Dependency(
                    description="child-service",
                    remote=RemoteConfig(
                        repo_name="child-service",
                        repo_link=f"file://{child_service_repo_path}",
                        branch="main",
                    ),
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
        install_and_verify_dependencies(service)
        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            "child-service": set(),
            "parent-service": {"child-service"},
            "grandparent-service": {"parent-service", "child-service"},
        }

        assert dependency_graph.get_starting_order() == [
            "child-service",
            "parent-service",
            "grandparent-service",
        ]


def test_construct_dependency_graph_complex(
    tmp_path: Path,
) -> None:
    parent_service_repo_path = tmp_path / "parent-service-repo"
    child_service_repo_path = tmp_path / "child-service-repo"
    grandparent_service_repo_path = tmp_path / "grandparent-service-repo"
    create_mock_git_repo("blank_repo", parent_service_repo_path)
    create_mock_git_repo("blank_repo", child_service_repo_path)
    create_mock_git_repo("blank_repo", grandparent_service_repo_path)
    parent_service_repo_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "parent-service",
            "dependencies": {
                "child-service": {
                    "description": "child-service",
                    "remote": {
                        "repo_name": "child-service",
                        "repo_link": f"file://{child_service_repo_path}",
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
    child_service_repo_config = {
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
    grandparent_service_repo_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "grandparent-service",
            "dependencies": {
                "parent-service": {
                    "description": "parent-service",
                    "remote": {
                        "repo_name": "parent-service",
                        "repo_link": f"file://{parent_service_repo_path}",
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
    create_config_file(parent_service_repo_path, parent_service_repo_config)
    create_config_file(child_service_repo_path, child_service_repo_config)
    create_config_file(grandparent_service_repo_path, grandparent_service_repo_config)
    run_git_command(["add", "."], cwd=parent_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=parent_service_repo_path
    )
    run_git_command(["add", "."], cwd=child_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=child_service_repo_path
    )
    run_git_command(["add", "."], cwd=grandparent_service_repo_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=grandparent_service_repo_path
    )
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
                        repo_link=f"file://{child_service_repo_path}",
                        branch="main",
                    ),
                ),
                "grandparent-service": Dependency(
                    description="grandparent-service",
                    remote=RemoteConfig(
                        repo_name="grandparent-service",
                        repo_link=f"file://{grandparent_service_repo_path}",
                        branch="main",
                    ),
                ),
                "complex-service": Dependency(
                    description="complex-service",
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
        install_and_verify_dependencies(service)
        dependency_graph = construct_dependency_graph(service, ["default"])
        assert dependency_graph.graph == {
            "child-service": set(),
            "parent-service": {"child-service"},
            "grandparent-service": {"parent-service"},
            "complex-service": {"grandparent-service", "child-service"},
        }
        assert dependency_graph.get_starting_order() == [
            "child-service",
            "parent-service",
            "grandparent-service",
            "complex-service",
        ]
