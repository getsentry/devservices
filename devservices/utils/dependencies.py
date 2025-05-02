from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import TextIO
from typing import TypeGuard

from sentry_sdk import capture_message
from sentry_sdk import set_context

from devservices.configs.service_config import Dependency
from devservices.configs.service_config import load_service_config_from_file
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEPENDENCY_CONFIG_VERSION
from devservices.constants import DEPENDENCY_GIT_PARTIAL_CLONE_CONFIG_OPTIONS
from devservices.constants import DEVSERVICES_DEPENDENCIES_CACHE_DIR
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import LOGGER_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import ConfigValidationError
from devservices.exceptions import DependencyError
from devservices.exceptions import DependencyNotInstalledError
from devservices.exceptions import FailedToSetGitConfigError
from devservices.exceptions import InvalidDependencyConfigError
from devservices.exceptions import ModeDoesNotExistError
from devservices.exceptions import UnableToCloneDependencyError
from devservices.utils.file_lock import lock
from devservices.utils.services import find_matching_service
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables

RELEVANT_GIT_CONFIG_KEYS = [
    "init.defaultbranch",
    "core.sparsecheckout",
    "remote.origin.url",
    "remote.origin.fetch",
    "remote.origin.promisor",
    "remote.origin.partialclonefilter",
    "protocol.version",
    "extensions.partialclone",
]


class DependencyType(str, Enum):
    SERVICE = "service"
    COMPOSE = "compose"


@dataclass(frozen=True, eq=True)
class DependencyNode:
    name: str
    dependency_type: DependencyType

    def __str__(self) -> str:
        return self.name


class DependencyGraph:
    def __init__(self) -> None:
        self.graph: dict[DependencyNode, set[DependencyNode]] = dict()

    def add_node(self, node: DependencyNode) -> None:
        if node not in self.graph:
            self.graph[node] = set()

    def add_edge(self, from_node: DependencyNode, to_node: DependencyNode) -> None:
        if from_node == to_node:
            # TODO: Add a better exception
            raise ValueError("Cannot add an edge from a node to itself")
        if from_node not in self.graph:
            self.add_node(from_node)
        if to_node not in self.graph:
            self.add_node(to_node)

        # TODO: Should we check for cycles here?

        self.graph[from_node].add(to_node)

    def topological_sort(self) -> list[DependencyNode]:
        in_degree = {service_name: 0 for service_name in self.graph}

        for service_node in self.graph.keys():
            for dependency_node in self.graph[service_node]:
                in_degree[dependency_node] += 1

        queue = deque(
            [
                dependency_node
                for dependency_node in self.graph
                if in_degree[dependency_node] == 0
            ]
        )
        topological_order = list()

        while queue:
            service_node = queue.popleft()
            topological_order.append(service_node)

            for dependency_node in self.graph[service_node]:
                in_degree[dependency_node] -= 1
                if in_degree[dependency_node] == 0:
                    queue.append(dependency_node)

        if len(topological_order) != len(self.graph):
            # TODO: Add a better exception
            raise ValueError("Cycle detected in the dependency graph")

        return topological_order

    def get_starting_order(self) -> list[DependencyNode]:
        return list(reversed(self.topological_sort()))


@dataclass(frozen=True)
class InstalledRemoteDependency:
    service_name: str
    repo_path: str
    mode: str = "default"


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
            self.sparse_checkout_manager.set_sparse_checkout(self.sparse_pattern)

    def get_relevant_config(self) -> dict[str, str]:
        """
        Get the relevant git config entries (to avoid logging sensitive information)
        """
        git_config = (
            subprocess.check_output(
                ["git", "config", "--list"],
                cwd=self.repo_dir,
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )
        git_config_dict = dict()
        for line in git_config.split("\n"):
            if not line:
                continue
            key, value = line.split("=")
            if key in RELEVANT_GIT_CONFIG_KEYS:
                git_config_dict[key] = value
        return git_config_dict

    def _set_config(self, key: str, value: str) -> None:
        """
        Set a git config option for the repo
        """
        try:
            _run_command(["git", "config", key, value], cwd=self.repo_dir)
        except subprocess.CalledProcessError as e:
            raise FailedToSetGitConfigError from e


def install_and_verify_dependencies(
    service: Service,
    force_update_dependencies: bool = False,
    modes: list[str] | None = None,
) -> set[InstalledRemoteDependency]:
    """
    Install and verify dependencies for a service
    """
    if modes is None:
        modes = ["default"]
    mode_dependencies = set()
    for mode in modes:
        if mode not in service.config.modes:
            raise ModeDoesNotExistError(
                service_name=service.name,
                mode=mode,
                available_modes=list(service.config.modes.keys()),
            )
        mode_dependencies.update(service.config.modes[mode])
    matching_dependencies = [
        dependency
        for dependency_key, dependency in list(service.config.dependencies.items())
        if dependency_key in mode_dependencies
    ]

    if force_update_dependencies:
        remote_dependencies = install_dependencies(matching_dependencies)
    else:
        are_dependencies_valid = verify_local_dependencies(matching_dependencies)
        if not are_dependencies_valid:
            # TODO: Figure out how to handle this case as installing dependencies may not be the right thing to do
            #       since the dependencies may have changed since the service was started.
            remote_dependencies = install_dependencies(matching_dependencies)
        else:
            remote_dependencies = get_installed_remote_dependencies(
                matching_dependencies
            )
    return remote_dependencies


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


def get_non_shared_remote_dependencies(
    service_to_stop: Service,
    remote_dependencies: set[InstalledRemoteDependency],
    exclude_local: bool,
) -> set[InstalledRemoteDependency]:
    state = State()
    starting_services = set(state.get_service_entries(StateTables.STARTING_SERVICES))
    started_services = set(state.get_service_entries(StateTables.STARTED_SERVICES))
    active_services = starting_services.union(started_services)
    # We don't care about the remote dependencies of the service we are stopping
    if service_to_stop.name in active_services:
        active_services.remove(service_to_stop.name)

    active_modes: dict[str, list[str]] = dict()
    for active_service in active_services:
        # TODO: We probably shouldn't use an OR here, but an AND
        starting_modes = state.get_active_modes_for_service(
            active_service, StateTables.STARTING_SERVICES
        )
        started_modes = state.get_active_modes_for_service(
            active_service, StateTables.STARTED_SERVICES
        )
        active_modes[active_service] = starting_modes or started_modes

    other_running_remote_dependencies: set[InstalledRemoteDependency] = set()
    base_running_service_names: set[str] = set()
    for started_service_name in active_services:
        started_service = find_matching_service(started_service_name)
        started_service_runtime = state.get_service_runtime(started_service_name)
        if exclude_local or started_service_runtime != ServiceRuntime.LOCAL:
            # TODO: In theory, we should only be able to run the base-service when a dependent service is running if
            # 1. the dependent service is using a mode that doesn't include the base-service
            # 2. the base-service is using a local runtime
            # But we don't restrict the other cases currently
            for dependency_name in service_to_stop.config.dependencies.keys():
                if dependency_name == started_service.config.service_name:
                    base_running_service_names.add(started_service_name)

        started_service_modes = active_modes[started_service_name]
        # Only consider the dependencies of the modes that are running
        started_service_dependencies: dict[str, Dependency] = dict()
        for started_service_mode in started_service_modes:
            for dependency_name in started_service.config.modes[started_service_mode]:
                started_service_dependencies[
                    dependency_name
                ] = started_service.config.dependencies[dependency_name]

        installed_remote_dependencies = get_installed_remote_dependencies(
            list(started_service_dependencies.values())
        )
        # TODO: There is an edge case here where there is a shared remote dependency with different modes
        other_running_remote_dependencies = other_running_remote_dependencies.union(
            installed_remote_dependencies
        )
    non_shared_remote_dependencies = remote_dependencies.difference(
        other_running_remote_dependencies
    )
    non_shared_remote_dependencies = {
        dependency
        for dependency in non_shared_remote_dependencies
        if dependency.service_name not in base_running_service_names
    }
    return non_shared_remote_dependencies


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
                service_name=service_config.service_name,
                repo_path=dependency_repo_dir,
                mode=remote_config.mode,
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

    if dependency.mode not in installed_config.modes:
        raise ModeDoesNotExistError(
            service_name=installed_config.service_name,
            mode=dependency.mode,
            available_modes=list(installed_config.modes.keys()),
        )

    active_nested_dependencies = [
        nested_dependency
        for nested_dependency_name, nested_dependency in installed_config.dependencies.items()
        if nested_dependency_name in installed_config.modes[dependency.mode]
    ]
    nested_remote_configs = _get_remote_configs(active_nested_dependencies)

    installed_dependencies: set[InstalledRemoteDependency] = set(
        [
            InstalledRemoteDependency(
                service_name=installed_config.service_name,
                repo_path=dependency_repo_dir,
                mode=dependency.mode,
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
        _run_command_with_retries(
            [
                "git",
                "fetch",
                "origin",
                dependency.branch,
                "--filter=blob:none",
                "--no-recurse-submodules",  # Avoid fetching submodules
            ],
            cwd=dependency_repo_dir,
        )
    except subprocess.CalledProcessError as e:
        # Try to set the git config context to help with debugging
        _try_set_git_config_context(git_config_manager)
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
            stderr=e.stderr,
        ) from e

    # Check if the local repo is up-to-date
    try:
        local_commit = _rev_parse(dependency_repo_dir, "HEAD")
    except subprocess.CalledProcessError as e:
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
            stderr=e.stderr,
        ) from e

    try:
        remote_commit = _rev_parse(dependency_repo_dir, "FETCH_HEAD")
    except subprocess.CalledProcessError as e:
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
            stderr=e.stderr,
        ) from e

    if local_commit == remote_commit:
        # Already up-to-date, don't pull anything
        logger = logging.getLogger(LOGGER_NAME)
        logger.debug(
            "Dependency %s is already up-to-date, not pulling anything",
            dependency.repo_name,
        )
        return

    # If it's not up-to-date, checkout the latest changes (forcibly)
    try:
        _run_command(["git", "checkout", "-f", "FETCH_HEAD"], cwd=dependency_repo_dir)
    except subprocess.CalledProcessError as e:
        raise DependencyError(
            repo_name=dependency.repo_name,
            repo_link=dependency.repo_link,
            branch=dependency.branch,
            stderr=e.stderr,
        ) from e


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
            raise UnableToCloneDependencyError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
                stderr=e.stderr,
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

        try:
            _run_command(
                ["git", "checkout", dependency.branch],
                cwd=temp_dir,
            )
        except subprocess.CalledProcessError as e:
            raise DependencyError(
                repo_name=dependency.repo_name,
                repo_link=dependency.repo_link,
                branch=dependency.branch,
                stderr=e.stderr,
            ) from e

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


def _rev_parse(repo_dir: str, ref: str) -> str:
    logger = logging.getLogger(LOGGER_NAME)
    logger.debug("Parsing revision for %s (%s)", ref, repo_dir)
    rev = (
        subprocess.check_output(
            ["git", "rev-parse", ref], cwd=repo_dir, stderr=subprocess.PIPE
        )
        .strip()
        .decode()
    )
    logger.debug("Parsed revision %s for %s (%s)", rev, ref, repo_dir)
    return rev


def _run_command(
    cmd: list[str], cwd: str, stdout: int | TextIO | None = subprocess.DEVNULL
) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.debug("Running command: %s in %s", " ".join(cmd), cwd)
    subprocess.run(cmd, cwd=cwd, check=True, stdout=stdout, stderr=subprocess.PIPE)


def _run_command_with_retries(
    cmd: list[str],
    cwd: str,
    stdout: int | TextIO | None = subprocess.DEVNULL,
    retries: int = 3,
    backoff: int = 2,
) -> None:
    for i in range(retries):
        try:
            _run_command(cmd, cwd=cwd, stdout=stdout)
            break
        except subprocess.CalledProcessError as e:
            logger = logging.getLogger(LOGGER_NAME)
            logger.debug(
                "Attempt %s of %s for %s failed: %s", i + 1, retries, cmd, e.stderr
            )
            capture_message(
                f"Attempt {i + 1} of {retries} for {cmd} failed: {e.stderr}",
                level="warning",
            )
            if i == retries - 1:
                raise e
            time.sleep(backoff**i)


def _try_set_git_config_context(
    git_config_manager: GitConfigManager,
) -> None:
    try:
        git_config = git_config_manager.get_relevant_config()
        set_context("git_config", git_config)
    except subprocess.CalledProcessError as e:
        logger = logging.getLogger(LOGGER_NAME)
        logger.exception(e)


def get_remote_dependency_config(remote_config: RemoteConfig) -> ServiceConfig:
    dependency_repo_dir = os.path.join(
        DEVSERVICES_DEPENDENCIES_CACHE_DIR,
        DEPENDENCY_CONFIG_VERSION,
        remote_config.repo_name,
    )
    return load_service_config_from_file(dependency_repo_dir)


def construct_dependency_graph(service: Service, modes: list[str]) -> DependencyGraph:
    dependency_graph = DependencyGraph()

    def _construct_dependency_graph(
        service_config: ServiceConfig, modes: list[str]
    ) -> None:
        service_mode_dependencies = set()
        for mode in modes:
            service_mode_dependencies.update(service_config.modes.get(mode, []))
        for dependency_name, dependency in service_config.dependencies.items():
            # Skip the dependency if it's not in the modes (since it may not be installed and we don't care about it)
            if dependency_name not in service_mode_dependencies:
                continue
            dependency_graph.add_edge(
                DependencyNode(
                    name=service_config.service_name,
                    dependency_type=DependencyType.SERVICE,
                ),
                DependencyNode(
                    name=dependency_name,
                    dependency_type=DependencyType.SERVICE
                    if _has_remote_config(dependency.remote)
                    else DependencyType.COMPOSE,
                ),
            )
            if _has_remote_config(dependency.remote):
                dependency_config = get_remote_dependency_config(dependency.remote)
                _construct_dependency_graph(dependency_config, [dependency.remote.mode])

    _construct_dependency_graph(service.config, modes)
    return dependency_graph
