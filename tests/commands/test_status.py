from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.status import format_uptime
from devservices.commands.status import generate_service_status_details
from devservices.commands.status import generate_service_status_tree
from devservices.commands.status import generate_supervisor_status_details
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
from devservices.constants import DependencyType
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.dependencies import DependencyGraph
from devservices.utils.dependencies import DependencyNode
from devservices.utils.services import Service
from devservices.utils.state import State
from devservices.utils.state import StateTables
from devservices.utils.supervisor import ProcessInfo
from devservices.utils.supervisor import SupervisorProcessState
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
                    "redis": Dependency(
                        description="Redis",
                        dependency_type=DependencyType.COMPOSE,
                    ),
                    "clickhouse": Dependency(
                        description="Clickhouse",
                        dependency_type=DependencyType.COMPOSE,
                    ),
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
    process_statuses: dict[str, ProcessInfo] = {}
    result = generate_service_status_details(
        dependency, process_statuses, docker_compose_service_to_status, ""
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
    process_statuses: dict[str, ProcessInfo] = {}
    result = generate_service_status_details(
        dependency, process_statuses, docker_compose_service_to_status, ""
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
            {},
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
            {},
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
            {},
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
                    "redis": Dependency(
                        description="Redis",
                        dependency_type=DependencyType.COMPOSE,
                    ),
                    "clickhouse": Dependency(
                        description="Clickhouse",
                        dependency_type=DependencyType.COMPOSE,
                    ),
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


@mock.patch("devservices.commands.status.install_and_verify_dependencies")
@mock.patch(
    "devservices.commands.status.SupervisorManager.get_all_process_info",
    return_value={},
)
def test_status_dependency_error(
    mock_supervisor_get_all_process_info: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        config_file = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {},
                "modes": {"default": []},
            },
        }
        create_config_file(tmp_path / "test-service", config_file)
        os.chdir(tmp_path / "test-service")
        mock_install_and_verify_dependencies.side_effect = DependencyError(
            repo_name="test-service", repo_link=str(tmp_path), branch="main"
        )

        args = Namespace(service_name="test-service")
        with pytest.raises(SystemExit) as exc_info:
            status(args)

        assert exc_info.value.code == 1

        mock_install_and_verify_dependencies.assert_called_once()

        captured = capsys.readouterr()
        assert (
            f"DependencyError: test-service ({str(tmp_path)}) on main" in captured.out
        )


@mock.patch(
    "devservices.commands.status.install_and_verify_dependencies", return_value=set()
)
@mock.patch("devservices.commands.status.get_status_json_results")
@mock.patch("devservices.commands.status.generate_service_status_tree")
def test_status_docker_compose_error(
    mock_generate_service_status_tree: mock.Mock,
    mock_get_status_json_results: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )
        config_file = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {},
                "modes": {"default": []},
            },
        }
        create_config_file(tmp_path / "test-service", config_file)
        os.chdir(tmp_path / "test-service")
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


def test_generate_supervisor_status_details_running_program() -> None:
    dependency = DependencyNode(
        name="test-program",
        dependency_type=DependencyType.SUPERVISOR,
    )
    process_statuses: dict[str, ProcessInfo] = {
        "test-program": {
            "name": "test-program",
            "state": SupervisorProcessState.RUNNING,  # RUNNING
            "state_name": SupervisorProcessState.RUNNING.name,
            "description": "Test program description",
            "pid": 12345,
            "uptime": 3661,  # 1 hour, 1 minute, 1 second
            "start_time": 1234567890,
            "stop_time": 0,
            "group": "test-group",
        }
    }

    result = generate_supervisor_status_details(dependency, process_statuses, "")

    assert result == (
        f"{Color.BOLD}test-program{Color.RESET}:\n"
        "  Type: process\n"
        "  Status: running\n"
        "  PID: 12345\n"
        "  Uptime: 1h 1m 1s"
    )


def test_generate_supervisor_status_details_stopped_program() -> None:
    """Test supervisor status details for a stopped program."""
    dependency = DependencyNode(
        name="stopped-program",
        dependency_type=DependencyType.SUPERVISOR,
    )
    process_statuses: dict[str, ProcessInfo] = {
        "stopped-program": {
            "name": "stopped-program",
            "state": SupervisorProcessState.STOPPED,  # STOPPED
            "state_name": SupervisorProcessState.STOPPED.name,
            "description": "",
            "pid": 0,
            "uptime": 0,
            "start_time": 0,
            "stop_time": 1234567890,
            "group": "",
        }
    }

    result = generate_supervisor_status_details(dependency, process_statuses, "  ")

    assert result == (
        f"  {Color.BOLD}stopped-program{Color.RESET}:\n"
        "    Type: process\n"
        "    Status: stopped\n"
        "    PID: N/A\n"
        "    Uptime: 0s"
    )


def test_generate_supervisor_status_details_program_not_found() -> None:
    """Test supervisor status details when program is not found."""
    dependency = DependencyNode(
        name="missing-program",
        dependency_type=DependencyType.SUPERVISOR,
    )
    process_statuses: dict[str, ProcessInfo] = {
        "other-program": {
            "name": "other-program",
            "state": SupervisorProcessState.RUNNING,
            "state_name": SupervisorProcessState.RUNNING.name,
            "description": "",
            "pid": 12345,
            "uptime": 100,
            "start_time": 1234567890,
            "stop_time": 0,
            "group": "test",
        }
    }

    result = generate_supervisor_status_details(dependency, process_statuses, "")

    assert result == (
        f"{Color.BOLD}missing-program{Color.RESET}:\n"
        "  Type: process\n"
        "  Status: N/A (process not found)"
    )


def test_generate_supervisor_status_details_empty_programs_list() -> None:
    """Test supervisor status details with empty programs list."""
    dependency = DependencyNode(
        name="test-program",
        dependency_type=DependencyType.SUPERVISOR,
    )
    process_statuses: dict[str, ProcessInfo] = {}

    result = generate_supervisor_status_details(dependency, process_statuses, "")

    assert result == (
        f"{Color.BOLD}test-program{Color.RESET}:\n"
        "  Type: process\n"
        "  Status: N/A (process not found)"
    )


def test_generate_service_status_details_supervisor_dependency() -> None:
    """Test that supervisor dependencies are handled correctly in generate_service_status_details."""
    dependency = DependencyNode(
        name="test-supervisor-program",
        dependency_type=DependencyType.SUPERVISOR,
    )
    process_statuses: dict[str, ProcessInfo] = {
        "test-supervisor-program": {
            "name": "test-supervisor-program",
            "state": SupervisorProcessState.RUNNING,
            "state_name": SupervisorProcessState.RUNNING.name,
            "description": "Test supervisor program",
            "pid": 54321,
            "uptime": 120,
            "start_time": 1234567890,
            "stop_time": 0,
            "group": "supervisor-group",
        }
    }
    docker_compose_service_to_status: dict[str, ServiceStatusOutput] = {}

    result = generate_service_status_details(
        dependency, process_statuses, docker_compose_service_to_status, ""
    )

    assert result == (
        f"{Color.BOLD}test-supervisor-program{Color.RESET}:\n"
        "  Type: process\n"
        "  Status: running\n"
        "  PID: 54321\n"
        "  Uptime: 2m 0s"
    )


def test_format_uptime_zero_seconds() -> None:
    """Test format_uptime with zero seconds."""
    assert format_uptime(0) == "0s"


def test_format_uptime_seconds_only() -> None:
    """Test format_uptime with seconds only."""
    assert format_uptime(30) == "30s"


def test_format_uptime_minutes_and_seconds() -> None:
    """Test format_uptime with minutes and seconds."""
    assert format_uptime(90) == "1m 30s"  # 1 minute 30 seconds


def test_format_uptime_hours_minutes_seconds() -> None:
    """Test format_uptime with hours, minutes, and seconds."""
    assert format_uptime(3661) == "1h 1m 1s"  # 1 hour 1 minute 1 second


def test_format_uptime_days_hours_minutes_seconds() -> None:
    """Test format_uptime with days, hours, minutes, and seconds."""
    assert format_uptime(90061) == "1d 1h 1m 1s"  # 1 day 1 hour 1 minute 1 second


def test_format_uptime_exact_hour() -> None:
    """Test format_uptime with exact hour."""
    assert format_uptime(3600) == "1h 0m 0s"


def test_format_uptime_exact_day() -> None:
    """Test format_uptime with exact day."""
    assert format_uptime(86400) == "1d 0h 0m 0s"


def test_format_uptime_large_values() -> None:
    """Test format_uptime with large values."""
    # 10 days, 5 hours, 30 minutes, 45 seconds
    uptime = 10 * 86400 + 5 * 3600 + 30 * 60 + 45
    assert format_uptime(uptime) == "10d 5h 30m 45s"


@mock.patch("devservices.commands.status.SupervisorManager")
@mock.patch("devservices.commands.status.get_status_json_results")
def test_status_with_supervisor_programs(
    mock_get_status_json_results: mock.Mock,
    mock_supervisor_manager: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.utils.state.DEVSERVICES_LOCAL_DIR", str(tmp_path / "local")
        ),
        mock.patch(
            "devservices.commands.status.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
    ):
        state = State()
        state.update_service_entry(
            "test-service", "default", StateTables.STARTED_SERVICES
        )

        test_service_repo_path = tmp_path / "code" / "test-service"
        create_mock_git_repo("blank_repo", test_service_repo_path)

        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "test-service",
                "dependencies": {
                    "clickhouse": {"description": "Clickhouse"},
                    "worker": {"description": "Background worker"},
                },
                "modes": {"default": ["clickhouse", "worker"]},
            },
            "x-programs": {
                "worker": {
                    "command": "python worker.py",
                },
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        create_config_file(test_service_repo_path, config)

        # Commit the config files so find_matching_service can discover them
        run_git_command(["add", "."], cwd=test_service_repo_path)
        run_git_command(["commit", "-m", "Add config"], cwd=test_service_repo_path)

        # Mock supervisor programs status
        mock_process_statuses: dict[str, ProcessInfo] = {
            "worker": {
                "name": "worker",
                "state": SupervisorProcessState.RUNNING,
                "state_name": "RUNNING",
                "description": "Background worker process",
                "pid": 12345,
                "uptime": 3600,  # 1 hour
                "start_time": 1234567890,
                "stop_time": 0,
                "group": "workers",
            },
        }

        # Mock docker compose status for clickhouse (matching the config)
        mock_docker_status = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"Service": "clickhouse", "State": "running", "Health": "healthy", "Name": "test-service-clickhouse-1", "RunningFor": "2 hours ago", "Publishers": [{"URL": "127.0.0.1", "PublishedPort": 9000, "TargetPort": 9000, "Protocol": "tcp"}]}\n',
                stderr="",
            )
        ]

        # Set up mocks
        mock_get_status_json_results.return_value = mock_docker_status
        mock_supervisor_manager.return_value.get_all_process_info.return_value = (
            mock_process_statuses
        )

        # Change to service directory so find_matching_service can find the config
        original_cwd = os.getcwd()
        os.chdir(test_service_repo_path)

        try:
            # Call the status function
            args = Namespace(service_name="test-service")
            status(args)
        finally:
            os.chdir(original_cwd)

        # Verify the output
        captured = capsys.readouterr()
        output = captured.out

        # Assert on the entire expected output block
        expected_output = (
            f"{Color.BOLD}test-service{Color.RESET}:\n"
            "  Type: service\n"
            "  Runtime: local\n"
            f"  {Color.BOLD}clickhouse{Color.RESET}:\n"
            "    Type: container\n"
            "    Status: running\n"
            f"    Health: {Color.GREEN}healthy{Color.RESET}\n"
            "    Container: test-service-clickhouse-1\n"
            "    Uptime: 2 hours ago\n"
            "    Ports:\n"
            "      127.0.0.1:9000 -> 9000/tcp\n"
            f"  {Color.BOLD}worker{Color.RESET}:\n"
            "    Type: process\n"
            "    Status: running\n"
            "    PID: 12345\n"
            "    Uptime: 1h 0m 0s\n"
        )
        assert output == expected_output
