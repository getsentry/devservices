from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TextIO
from typing import TypeGuard

from devservices.configs.service_config import Dependency
from devservices.configs.service_config import load_service_config_from_file
from devservices.configs.service_config import RemoteConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.exceptions import DependencyError
from devservices.exceptions import DependencyNotInstalledError
from devservices.exceptions import FailedToSetGitConfigError
from devservices.exceptions import InvalidDependencyConfigError
from devservices.utils.file_lock import lock


@dataclass(frozen=True)
class InstalledRemoteDependency:
    service_name: str
    repo_path: str


class SparseCheckoutManager:
    """
    Manages sparse checkout for a repo
    """

    def __init__(self, repo_dir: str):
        self.repo_dir = repo_dir

    def init_sparse_checkout(self) -> None:
        """
        Initialize sparse checkout for the repo
        """
        _run_command(["git", "sparse-checkout", "init"], cwd=self.repo_dir)

    def set_sparse_checkout(self, pattern: str) -> None:
        """
        Set sparse checkout patterns for the repo
        """
        self.init_sparse_checkout()
        _run_command(["git", "sparse-checkout", "set", pattern], cwd=self.repo_dir)

    def clear_sparse_checkout(self) -> None:
        """
        Clear sparse checkout for the repo
        """
        try:
            _run_command(["git", "sparse-checkout", "clear"], cwd=self.repo_dir)
        except subprocess.CalledProcessError:
            # Ignore if it fails as it might not be set
            pass


class GitConfigManager:
    """
    Manages git config for a repo
    """

    def __init__(
        self,
        repo_dir: str,
        config_options: dict[str, str],
        sparse_pattern: str | None = None,
    ) -> None:
        self.repo_dir = repo_dir
        self.config_options = config_options
        self.sparse_pattern = sparse_pattern
        self.sparse_checkout_manager = SparseCheckoutManager(repo_dir)

    def ensure_config(self) -> None:
        """
        Ensure that the git config is set correctly for the repo
        """
        # Otherwise, set the config options
        for key, value in self.config_options.items():
            self._set_config(key, value)

        if self.sparse_pattern:
            # Clear the sparse checkout if it's already set (to avoid conflicts)
            self.sparse_checkout_manager.clear_sparse_checkout()
            self.sparse_checkout_manager.set_sparse_checkout(self.sparse_pattern)

    def _set_config(self, key: str, value: str) -> None:
        """
        Set a git config option for the repo
        """
        try:
            _run_command(["git", "config", key, value], cwd=self.repo_dir)
        except subprocess.CalledProcessError as e:
            raise FailedToSetGitConfigError from e


def verify_local_dependency(remote_config: RemoteConfig) -> bool:
    local_dependency_path = os.path.join(
        DEVSERVICES_DEPENDENCIES_CACHE_DIR,
        DEPENDENCY_CONFIG_VERSION,
        remote_config.repo_name,
        DEVSERVICES_DIR_NAME,
        CONFIG_FILE_NAME,
    )
    return os.path.exists(local_dependency_path)


def verify_local_dependencies(dependencies: list[Dependency]) -> bool:
    remote_configs = _get_remote_configs(dependencies)

    # Short circuit to avoid doing unnecessary work
    if len(remote_configs) == 0:
        return True

    if not os.path.exists(DEVSERVICES_DEPENDENCIES_CACHE_DIR):
        return False

    return all(
        verify_local_dependency(remote_config) for remote_config in remote_configs
    )


def get_installed_remote_dependencies(
    dependencies: list[Dependency],
) -> set[InstalledRemoteDependency]:
    installed_dependencies: set[InstalledRemoteDependency] = set()
    remote_configs = _get_remote_configs(dependencies)
    while len(remote_configs) > 0:
        remote_config = remote_configs.pop()
        dependency_repo_dir = os.path.join(
            DEVSERVICES_DEPENDENCIES_CACHE_DIR,
            DEPENDENCY_CONFIG_VERSION,
            remote_config.repo_name,
        )
        if not verify_local_dependency(remote_config):
            # TODO: what should we do if the local dependency isn't installed correctly?
            raise DependencyNotInstalledError(
                repo_name=remote_config.repo_name,
                repo_link=remote_config.repo_link,
                branch=remote_config.branch,
            )
        try:
            service_config = load_service_config_from_file(dependency_repo_dir)
        except (ConfigNotFoundError, ConfigParseError, ConfigValidationError) as e:
            raise InvalidDependencyConfigError(
                repo_name=remote_config.repo_name,
                repo_link=remote_config.repo_link,
                branch=remote_config.branch,
            ) from e
        installed_dependencies.add(
            InstalledRemoteDependency(
                service_name=service_config.service_name, repo_path=dependency_repo_dir
            )
        )
        nested_remote_configs = _get_remote_configs(
            list(service_config.dependencies.values())
        )
        remote_configs.extend(nested_remote_configs)

    return installed_dependencies


def install_dependencies(
    dependencies: list[Dependency],
) -> set[InstalledRemoteDependency]:
    remote_configs = _get_remote_configs(dependencies)

    # Short circuit to avoid doing unnecessary work
    if len(remote_configs) == 0:
        return set()

    os.makedirs(DEVSERVICES_DEPENDENCIES_CACHE_DIR, exist_ok=True)

    installed_dependencies: set[InstalledRemoteDependency] = set()

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(install_dependency, dependency)
            for dependency in remote_configs
        ]
        for future in as_completed(futures):
            try:
                nested_installed_dependencies = future.result()
                installed_dependencies = installed_dependencies.union(
                    nested_installed_dependencies
                )
            except DependencyError as e:
                raise e
    return installed_dependencies


def install_dependency(dependency: RemoteConfig) -> set[InstalledRemoteDependency]:
    dependency_repo_dir = os.path.join(
        DEVSERVICES_DEPENDENCIES_CACHE_DIR,
        DEPENDENCY_CONFIG_VERSION,
        dependency.repo_name,
    )

    os.makedirs(DEVSERVICES_DEPENDENCIES_CACHE_DIR, exist_ok=True)

    # Ensure that only one process is installing a specific dependency at a time
    # TODO: This is a very broad lock, we should consider making it more granular to enable faster installs
    # TODO: Ideally we would simply not re-install something that is being currently being installed or was recently installed
    lock_path = os.path.join(
        DEVSERVICES_DEPENDENCIES_CACHE_DIR, f"{dependency.repo_name}.lock"
    )
    with lock(lock_path):
        if (
            os.path.exists(dependency_repo_dir)
            and _is_valid_repo(dependency_repo_dir)
            and _has_valid_config_file(dependency_repo_dir)
        ):
            _update_dependency(dependency, dependency_repo_dir)
        else:
            _checkout_dependency(dependency, dependency_repo_dir)

        if not verify_local_dependency(dependency):
            # TODO: what should we do if the local dependency isn't installed correctly?
            raise DependencyNotInstalledError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
            )

        # Once the dependency is installed, install its dependencies (recursively)
        try:
            installed_config = load_service_config_from_file(dependency_repo_dir)
        except (ConfigNotFoundError, ConfigParseError, ConfigValidationError) as e:
            # TODO: This happens when the dependency has an invalid config
            raise InvalidDependencyConfigError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
            ) from e

    nested_dependencies = list(installed_config.dependencies.values())
    nested_remote_configs = _get_remote_configs(nested_dependencies)

    installed_dependencies: set[InstalledRemoteDependency] = set(
        [
            InstalledRemoteDependency(
                service_name=installed_config.service_name,
                repo_path=dependency_repo_dir,
            )
        ]
    )

    with ThreadPoolExecutor() as nested_executor:
        nested_futures = [
            nested_executor.submit(install_dependency, nested_remote_config)
            for nested_remote_config in nested_remote_configs
        ]
        for nested_future in as_completed(nested_futures):
            try:
                nested_installed_dependencies = nested_future.result()
                installed_dependencies = installed_dependencies.union(
                    nested_installed_dependencies
                )
            except DependencyError as e:
                raise e
    return installed_dependencies


def _update_dependency(
    dependency: RemoteConfig,
    dependency_repo_dir: str,
) -> None:
    git_config_manager = GitConfigManager(
        dependency_repo_dir,
        DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS,
        f"{DEVSERVICES_DIR_NAME}/",
    )
    try:
        git_config_manager.ensure_config()
    except FailedToSetGitConfigError as e:
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
        ) from e
    try:
        _run_command(
            ["git", "fetch", "origin", dependency.branch, "--filter=blob:none"],
            cwd=dependency_repo_dir,
        )
    except subprocess.CalledProcessError as e:
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
        ) from e

    # Check if the local repo is up-to-date
    local_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=dependency_repo_dir,
        stderr=subprocess.PIPE,
    ).strip()

    remote_commit = subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD"],
        cwd=dependency_repo_dir,
        stderr=subprocess.PIPE,
    ).strip()

    if local_commit == remote_commit:
        # Already up-to-date, don't pull anything
        return

    # If it's not up-to-date, checkout the latest changes (forcibly)
    _run_command(["git", "checkout", "-f", "FETCH_HEAD"], cwd=dependency_repo_dir)


def _checkout_dependency(
    dependency: RemoteConfig,
    dependency_repo_dir: str,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            _run_command(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    dependency.repo_link,
                    temp_dir,
                ],
                cwd=temp_dir,
            )
        except subprocess.CalledProcessError as e:
            raise DependencyError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
            ) from e

        # Setup config for partial clone and sparse checkout
        git_config_manager = GitConfigManager(
            temp_dir,
            DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS,
            f"{DEVSERVICES_DIR_NAME}/",
        )
        try:
            git_config_manager.ensure_config()
        except FailedToSetGitConfigError as e:
            raise DependencyError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
            ) from e

        _run_command(
            ["git", "checkout", dependency.branch],
            cwd=temp_dir,
        )

        # Clean up the existing directory if it exists
        if os.path.exists(dependency_repo_dir):
            shutil.rmtree(dependency_repo_dir)
        # Copy the cloned repo to the dependency cache directory
        try:
            shutil.copytree(temp_dir, dst=dependency_repo_dir)
        except FileExistsError as e:
            raise DependencyError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
            ) from e


def _is_valid_repo(path: str) -> bool:
    if not os.path.exists(os.path.join(path, ".git")):
        return False
    try:
        _run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
        return True
    except subprocess.CalledProcessError:
        return False


def _has_valid_config_file(path: str) -> bool:
    return os.path.exists(os.path.join(path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME))


def _get_remote_configs(dependencies: list[Dependency]) -> list[RemoteConfig]:
    return [
        dependency.remote
        for dependency in dependencies
        if _has_remote_config(dependency.remote)
    ]


def _has_remote_config(remote_config: RemoteConfig | None) -> TypeGuard[RemoteConfig]:
    return remote_config is not None


def _run_command(
    cmd: list[str], cwd: str, stdout: int | TextIO | None = subprocess.DEVNULL
) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, stdout=stdout, stderr=subprocess.DEVNULL)
