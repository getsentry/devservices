from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.status import generate_service_status_details
from devservices.commands.status import generate_service_status_tree
from devservices.commands.status import get_status_json_results
from devservices.commands.status import handle_started_service
from devservices.commands.status import parse_docker_compose_status
from devservices.commands.status import process_service_with_local_runtime
from devservices.commands.status import ServiceStatusOutput
from devservices.commands.status import status
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import ServiceConfig
from devservices.constants import Color
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.dependencies import DependencyGraph
from devservices.utils.dependencies import DependencyNode
from devservices.utils.dependencies import DependencyType
from devservices.utils.services import Service
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


def test_get_status_json_results(
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        test_service_repo_path = tmp_path / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        service_path = tmp_path / "test-service"
        create_config_file(service_path, config)
        run_git_command(["add", "."], cwd=test_service_repo_path)
        run_git_command(["commit", "-m", "Initial commit"], cwd=test_service_repo_path)
        service = Service(
            name="test-service",
            repo_path=str(test_service_repo_path),
            config=ServiceConfig(
                version=0.1,
                service_name="test-service",
                dependencies={
                    "redis": Dependency(description="Redis"),
                    "clickhouse": Dependency(description="Clickhouse"),
                },
                modes={"default": ["redis", "clickhouse"], "test": ["redis"]},
            ),
        )

        results = get_status_json_results(service, set(), ["redis", "clickhouse"])
        assert len(results) == 1
        assert results[0].args == [
            "docker",
            "compose",
            "-p",
            "test-service",
            "-f",
            f"{test_service_repo_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
            "ps",
            "clickhouse",
            "redis",
            "--format",
            "json",
        ]
        assert results[0].returncode == 0
        assert results[0].stdout == ""
        assert results[0].stderr == ""


def test_parse_docker_compose_status() -> None:
    mock_status = [
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Service": "redis", "State": "running", "Health": "healthy", "Name": "redis", "RunningFor": "2 days ago", "Publishers": []}\n',
        ),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Service": "kafka", "State": "running", "Health": "healthy", "Name": "kafka", "RunningFor": "2 days ago", "Publishers": []}\n',
        ),
    ]
    expected_output: dict[str, ServiceStatusOutput] = {
        "kafka": {
            "Service": "kafka",
            "State": "running",
            "Health": "healthy",
            "Name": "kafka",
            "RunningFor": "2 days ago",
            "Publishers": [],
        },
        "redis": {
            "Service": "redis",
            "State": "running",
            "Health": "healthy",
            "Name": "redis",
            "RunningFor": "2 days ago",
            "Publishers": [],
        },
    }
    assert parse_docker_compose_status(mock_status) == expected_output


def test_parse_docker_compose_status_missing_stdout() -> None:
    mock_status = [
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
        ),
    ]
    assert parse_docker_compose_status(mock_status) == {}


def test_generate_service_status_details() -> None:
    dependency = DependencyNode(
        name="test-service",
        dependency_type=DependencyType.SERVICE,
    )
    docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {
        "test-service": {
            "Service": "test-service",
            "State": "running",
            "Health": "healthy",
            "Name": "test-container",
            "RunningFor": "2 days ago",
            "Publishers": [
                {
                    "URL": "127.0.0.1",
                    "PublishedPort": 8080,
                    "TargetPort": 8080,
                    "Protocol": "tcp",
                }
            ],
        }
    }
    result = generate_service_status_details(
        dependency, docker_compose_service_to_status, ""
    )
    assert result == (
        f"{Color.BOLD}test-service{Color.RESET}:\n"
        "  Type: container\n"
        "  Status: running\n"
        f"  Health: {Color.GREEN}healthy{Color.RESET}\n"
        "  Container: test-container\n"
        "  Uptime: 2 days ago\n"
        "  Ports:\n"
        "    127.0.0.1:8080 -> 8080/tcp"
    )


def test_generate_service_status_details_missing_status() -> None:
    dependency = DependencyNode(
        name="test-service",
        dependency_type=DependencyType.SERVICE,
    )
    docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {}
    result = generate_service_status_details(
        dependency, docker_compose_service_to_status, ""
    )
    assert result == (
        f"{Color.BOLD}test-service{Color.RESET}:\n"
        "  Type: container\n"
        "  Status: N/A"
    )


def test_generate_service_status_tree_no_child_service(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        parent_compose = DependencyNode(
            name="parent-container",
            dependency_type=DependencyType.COMPOSE,
        )
        parent_service = DependencyNode(
            name="parent-service",
            dependency_type=DependencyType.SERVICE,
        )
        dependency_graph = DependencyGraph()
        dependency_graph.add_edge(parent_service, parent_compose)
        docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {
            "parent-container": {
                "Service": "parent-container",
                "State": "running",
                "Health": "healthy",
                "Name": "parent-container",
                "RunningFor": "2 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8080,
                        "TargetPort": 8080,
                        "Protocol": "tcp",
                    },
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8081,
                        "TargetPort": 8081,
                        "Protocol": "tcp",
                    },
                ],
            },
        }
        result = generate_service_status_tree(
            "parent-service",
            dependency_graph,
            docker_compose_service_to_status,
            "",
        )
        assert result == (
            f"{Color.BOLD}parent-service{Color.RESET}:\n"
            "  Type: service\n"
            "  Runtime: local\n"
            f"  {Color.BOLD}parent-container{Color.RESET}:\n"
            "    Type: container\n"
            "    Status: running\n"
            f"    Health: {Color.GREEN}healthy{Color.RESET}\n"
            "    Container: parent-container\n"
            "    Uptime: 2 days ago\n"
            "    Ports:\n"
            "      127.0.0.1:8080 -> 8080/tcp\n"
            "      127.0.0.1:8081 -> 8081/tcp"
        )


def test_generate_service_status_tree_with_child_service(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        parent_compose = DependencyNode(
            name="parent-container",
            dependency_type=DependencyType.COMPOSE,
        )
        parent_service = DependencyNode(
            name="parent-service",
            dependency_type=DependencyType.SERVICE,
        )
        child_service = DependencyNode(
            name="child-service",
            dependency_type=DependencyType.SERVICE,
        )
        child_compose = DependencyNode(
            name="child-container",
            dependency_type=DependencyType.COMPOSE,
        )
        dependency_graph = DependencyGraph()
        dependency_graph.add_edge(parent_service, parent_compose)
        dependency_graph.add_edge(parent_service, child_service)
        dependency_graph.add_edge(child_service, child_compose)
        docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {
            "parent-container": {
                "Service": "parent-container",
                "State": "running",
                "Health": "healthy",
                "Name": "parent-container",
                "RunningFor": "2 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8080,
                        "TargetPort": 8080,
                        "Protocol": "tcp",
                    },
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8081,
                        "TargetPort": 8081,
                        "Protocol": "tcp",
                    },
                ],
            },
            "child-container": {
                "Service": "child-container",
                "State": "running",
                "Health": "unhealthy",
                "Name": "child-container",
                "RunningFor": "2 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8082,
                        "TargetPort": 8082,
                        "Protocol": "tcp",
                    },
                ],
            },
        }
        result = generate_service_status_tree(
            "parent-service",
            dependency_graph,
            docker_compose_service_to_status,
            "",
        )
        assert result == (
            f"{Color.BOLD}parent-service{Color.RESET}:\n"
            "  Type: service\n"
            "  Runtime: local\n"
            f"  {Color.BOLD}parent-container{Color.RESET}:\n"
            "    Type: container\n"
            "    Status: running\n"
            f"    Health: {Color.GREEN}healthy{Color.RESET}\n"
            "    Container: parent-container\n"
            "    Uptime: 2 days ago\n"
            "    Ports:\n"
            "      127.0.0.1:8080 -> 8080/tcp\n"
            "      127.0.0.1:8081 -> 8081/tcp\n"
            f"  {Color.BOLD}child-service{Color.RESET}:\n"
            "    Type: service\n"
            "    Runtime: containerized\n"
            f"    {Color.BOLD}child-container{Color.RESET}:\n"
            "      Type: container\n"
            "      Status: running\n"
            f"      Health: {Color.RED}unhealthy{Color.RESET}\n"
            "      Container: child-container\n"
            "      Uptime: 2 days ago\n"
            "      Ports:\n"
            "        127.0.0.1:8082 -> 8082/tcp"
        )


def test_generate_service_status_tree_with_nested_child_services(
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        grandparent_compose = DependencyNode(
            name="grandparent-container",
            dependency_type=DependencyType.COMPOSE,
        )
        grandparent_service = DependencyNode(
            name="grandparent-service",
            dependency_type=DependencyType.SERVICE,
        )
        parent_compose = DependencyNode(
            name="parent-container",
            dependency_type=DependencyType.COMPOSE,
        )
        parent_service = DependencyNode(
            name="parent-service",
            dependency_type=DependencyType.SERVICE,
        )
        child_compose = DependencyNode(
            name="child-container",
            dependency_type=DependencyType.COMPOSE,
        )
        child_service = DependencyNode(
            name="child-service",
            dependency_type=DependencyType.SERVICE,
        )
        dependency_graph = DependencyGraph()
        dependency_graph.add_edge(grandparent_service, grandparent_compose)
        dependency_graph.add_edge(grandparent_service, parent_service)
        dependency_graph.add_edge(parent_service, parent_compose)
        dependency_graph.add_edge(parent_service, child_service)
        dependency_graph.add_edge(child_service, child_compose)

        docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {
            "grandparent-container": {
                "Service": "grandparent-container",
                "State": "running",
                "Health": "healthy",
                "Name": "grandparent-container",
                "RunningFor": "1 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8080,
                        "TargetPort": 8080,
                        "Protocol": "tcp",
                    },
                ],
            },
            "parent-container": {
                "Service": "parent-container",
                "State": "running",
                "Health": "healthy",
                "Name": "parent-container",
                "RunningFor": "3 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8081,
                        "TargetPort": 8081,
                        "Protocol": "tcp",
                    },
                ],
            },
            "child-container": {
                "Service": "child-container",
                "State": "running",
                "Health": "starting",
                "Name": "child-container",
                "RunningFor": "2 days ago",
                "Publishers": [
                    {
                        "URL": "127.0.0.1",
                        "PublishedPort": 8082,
                        "TargetPort": 8082,
                        "Protocol": "tcp",
                    },
                ],
            },
        }
        result = generate_service_status_tree(
            "grandparent-service",
            dependency_graph,
            docker_compose_service_to_status,
            "",
        )
        assert result == (
            f"{Color.BOLD}grandparent-service{Color.RESET}:\n"
            "  Type: service\n"
            "  Runtime: local\n"
            f"  {Color.BOLD}grandparent-container{Color.RESET}:\n"
            "    Type: container\n"
            "    Status: running\n"
            f"    Health: {Color.GREEN}healthy{Color.RESET}\n"
            "    Container: grandparent-container\n"
            "    Uptime: 1 days ago\n"
            "    Ports:\n"
            "      127.0.0.1:8080 -> 8080/tcp\n"
            f"  {Color.BOLD}parent-service{Color.RESET}:\n"
            "    Type: service\n"
            "    Runtime: containerized\n"
            f"    {Color.BOLD}parent-container{Color.RESET}:\n"
            "      Type: container\n"
            "      Status: running\n"
            f"      Health: {Color.GREEN}healthy{Color.RESET}\n"
            "      Container: parent-container\n"
            "      Uptime: 3 days ago\n"
            "      Ports:\n"
            "        127.0.0.1:8081 -> 8081/tcp\n"
            f"    {Color.BOLD}child-service{Color.RESET}:\n"
            "      Type: service\n"
            "      Runtime: containerized\n"
            f"      {Color.BOLD}child-container{Color.RESET}:\n"
            "        Type: container\n"
            "        Status: running\n"
            f"        Health: {Color.YELLOW}starting{Color.RESET}\n"
            "        Container: child-container\n"
            "        Uptime: 2 days ago\n"
            "        Ports:\n"
            "          127.0.0.1:8082 -> 8082/tcp"
        )


@mock.patch(
    "devservices.commands.status.get_status_json_results",
    return_value=[
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Project": "test-service", "Service": "clickhouse", "State": "running", "Health": "healthy", "Name": "test-service-clickhouse-1", "RunningFor": "1 days ago", "Publishers": [{"URL": "127.0.0.1", "PublishedPort": 8080, "TargetPort": 8080, "Protocol": "tcp"}]}\n{"Project": "test-service", "Service": "redis", "State": "running", "Health": "healthy", "Name": "test-service-redis-1", "RunningFor": "1 days ago", "Publishers": [{"URL": "127.0.0.1", "PublishedPort": 8081, "TargetPort": 8081, "Protocol": "tcp"}]}\n',
            stderr="",
        ),
    ],
)
@mock.patch("devservices.commands.status.find_matching_service")
def test_handle_started_service(
    mock_find_matching_service: mock.Mock,
    mock_get_status_json_results: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        test_service_repo_path = tmp_path / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        service_path = tmp_path / "test-service"
        create_config_file(service_path, config)
        run_git_command(["add", "."], cwd=test_service_repo_path)
        run_git_command(["commit", "-m", "Initial commit"], cwd=test_service_repo_path)
        service = Service(
            name="test-service",
            repo_path=str(test_service_repo_path),
            config=ServiceConfig(
                version=0.1,
                service_name="test-service",
                dependencies={
                    "redis": Dependency(description="Redis"),
                    "clickhouse": Dependency(description="Clickhouse"),
                },
                modes={"default": ["redis", "clickhouse"], "test": ["redis"]},
            ),
        )
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        dependency = DependencyNode(
            name="test-service",
            dependency_type=DependencyType.SERVICE,
        )
        mock_find_matching_service.return_value = service
        result = handle_started_service(dependency, "  ")
        assert result == (
            f"  {Color.BOLD}test-service{Color.RESET}:\n"
            "    Type: service\n"
            "    Runtime: local\n"
            f"    {Color.BOLD}clickhouse{Color.RESET}:\n"
            "      Type: container\n"
            "      Status: running\n"
            f"      Health: {Color.GREEN}healthy{Color.RESET}\n"
            "      Container: test-service-clickhouse-1\n"
            "      Uptime: 1 days ago\n"
            "      Ports:\n"
            "        127.0.0.1:8080 -> 8080/tcp\n"
            f"    {Color.BOLD}redis{Color.RESET}:\n"
            "      Type: container\n"
            "      Status: running\n"
            f"      Health: {Color.GREEN}healthy{Color.RESET}\n"
            "      Container: test-service-redis-1\n"
            "      Uptime: 1 days ago\n"
            "      Ports:\n"
            "        127.0.0.1:8081 -> 8081/tcp"
        )
        mock_find_matching_service.assert_called_once_with("test-service")


def test_handle_started_service_invalid_config(
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.commands.status.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        os.makedirs(str(tmp_path / "code" / "test-service"))
        dependency = DependencyNode(
            name="test-service",
            dependency_type=DependencyType.SERVICE,
        )
        result = handle_started_service(dependency, "  ")
        assert result == (
            "  \033[1mtest-service\033[0m:\n"
            "    Type: service\n"
            "    Status: N/A\n"
            "    Runtime: local"
        )


@mock.patch("devservices.commands.status.handle_started_service")
def test_process_service_with_local_runtime_started(
    mock_handle_started_service: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        dependency = DependencyNode(
            name="test-service",
            dependency_type=DependencyType.SERVICE,
        )
        mock_handle_started_service.return_value = "test-service is running"
        result = process_service_with_local_runtime(dependency, "  ")
        assert result == "test-service is running"
        mock_handle_started_service.assert_called_once_with(dependency, "  ")


def test_process_service_with_local_runtime_starting(
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTING_SERVICES
        )
        dependency = DependencyNode(
            name="test-service",
            dependency_type=DependencyType.SERVICE,
        )
        result = process_service_with_local_runtime(dependency, "  ")
        assert result == (
            f"  {Color.BOLD}test-service{Color.RESET}:\n"
            "    Type: service\n"
            "    Status: starting\n"
            "    Runtime: local"
        )


def test_process_service_with_local_runtime_not_active(
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        dependency = DependencyNode(
            name="test-service",
            dependency_type=DependencyType.SERVICE,
        )
        result = process_service_with_local_runtime(dependency, "  ")
        assert result == (
            f"  {Color.BOLD}test-service{Color.RESET}:\n"
            "    Type: service\n"
            "    Status: N/A\n"
            "    Runtime: local"
        )


def test_status_no_config_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False)

    with pytest.raises(SystemExit):
        status(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices status sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )


@mock.patch("devservices.commands.status.get_status_for_service")
@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_service_not_found(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    mock_get_status_for_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_find_matching_service.side_effect = ServiceNotFoundError("Service not found")

    args = Namespace(service_name="nonexistent-service")
    with pytest.raises(SystemExit) as exc_info:
        status(args)

    assert exc_info.value.code == 1

    mock_find_matching_service.assert_called_once_with("nonexistent-service")
    mock_install_and_verify_dependencies.assert_not_called()
    mock_get_status_for_service.assert_not_called()

    captured = capsys.readouterr()
    assert "Service not found" in captured.out


@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch("devservices.commands.status.install_and_verify_dependencies")
def test_status_dependency_error(
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        service = Service(
            name="test-service",
            repo_path=str(tmp_path),
            config=ServiceConfig(
                version=0.1,
                service_name="test-service",
                dependencies={},
                modes={"default": []},
            ),
        )
        mock_find_matching_service.return_value = service
        mock_install_and_verify_dependencies.side_effect = DependencyError(
            repo_name="test-service", repo_link=str(tmp_path), branch="main"
        )

        args = Namespace(service_name="test-service")
        with pytest.raises(SystemExit) as exc_info:
            status(args)

        assert exc_info.value.code == 1

        mock_find_matching_service.assert_called_once_with("test-service")
        mock_install_and_verify_dependencies.assert_called_once_with(service)

        captured = capsys.readouterr()
        assert (
            f"DependencyError: test-service ({str(tmp_path)}) on main" in captured.out
        )


@mock.patch("devservices.commands.status.find_matching_service")
@mock.patch(
    "devservices.commands.status.install_and_verify_dependencies", return_value=set()
)
@mock.patch("devservices.commands.status.get_status_json_results")
@mock.patch("devservices.commands.status.generate_service_status_tree")
def test_status_docker_compose_error(
    mock_generate_service_status_tree: mock.Mock,
    mock_get_status_json_results: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        service = Service(
            name="test-service",
            repo_path=str(tmp_path),
            config=ServiceConfig(
                version=0.1,
                service_name="test-service",
                dependencies={},
                modes={"default": []},
            ),
        )
        mock_find_matching_service.return_value = service
        mock_get_status_json_results.side_effect = DockerComposeError(
            command="docker compose ps",
            returncode=1,
            stdout="",
            stderr="Failed to get status for test-service: ",
        )

        args = Namespace(service_name="test-service")
        with pytest.raises(SystemExit) as exc_info:
            status(args)

        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Failed to get status for test-service: " in captured.out


@mock.patch("devservices.commands.status.get_status_for_service")
@mock.patch("devservices.commands.status.find_matching_service")
def test_status_service_not_running(
    mock_find_matching_service: mock.Mock,
    mock_get_status_for_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = Namespace(service_name="test-service")
    service = Service(
        name="test-service",
        repo_path=str(tmp_path),
        config=ServiceConfig(
            version=0.1,
            service_name="test-service",
            dependencies={},
            modes={"default": []},
        ),
    )
    mock_find_matching_service.return_value = service

    status(args)

    mock_find_matching_service.assert_called_once_with("test-service")
    mock_get_status_for_service.assert_not_called()

    captured = capsys.readouterr()
    assert "Status unavailable. test-service is not running standalone" in captured.out
