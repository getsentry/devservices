from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from subprocess import SubprocessError
from unittest import mock

import pytest

from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DependencyError
from devservices.exceptions import FailedToSetGitConfigError
from devservices.utils.dependencies import GitConfigManager
from devservices.utils.dependencies import install_dependency
from devservices.utils.dependencies import verify_local_dependencies
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        assert verify_local_dependencies([])


def test_verify_local_dependencies_no_remote_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        dependency = Dependency(
            description="Test dependency",
        )
        assert verify_local_dependencies([dependency])


def test_verify_local_dependencies_with_remote_dependencies(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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


def test_install_dependency_invalid_repo(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        remote_config = RemoteConfig(
            repo_name="test-repo", branch="main", repo_link="invalid-link"
        )
        with pytest.raises(SubprocessError):
            install_dependency(remote_config)


@mock.patch("devservices.utils.dependencies.GitConfigManager.ensure_config")
def test_install_dependency_git_config_failure(
    ensure_config_mock: mock.Mock, tmp_path: Path
) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
            f.write("\nEdited config file")

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
            assert f.read().endswith("\nEdited config file")


def test_install_dependency_basic_with_new_tracked_file(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
            f.write("\nEdited config file")

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
            assert f.read().endswith("\nEdited config file")


def test_install_dependency_basic_with_corrupted_repo(tmp_path: Path) -> None:
    with mock.patch(
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
        "devservices.utils.dependencies.DEVSERVICES_LOCAL_DEPENDENCIES_DIR",
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
