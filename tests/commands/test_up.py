from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.up import up
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.constants import HEALTHCHECK_TIMEOUT
from devservices.exceptions import ConfigError
from devservices.exceptions import ContainerHealthcheckFailedError
from devservices.exceptions import DependencyError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
@mock.patch(
    "devservices.utils.docker_compose.get_non_remote_services",
    return_value={"clickhouse", "redis"},
)
def test_up_simple(
    mock_get_non_remote_services: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=False
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                return_value=["container1", "container2"],
            ) as mock_get_container_names_for_project,
        ):
            up(args)

            mock_pull_dependency_images.assert_called_once_with(
                DockerComposeCommand(
                    full_command=[
                        "docker",
                        "compose",
                        "-p",
                        "example-service",
                        "-f",
                        f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "pull",
                        "clickhouse",
                        "redis",
                    ],
                    project_name="example-service",
                    config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["clickhouse", "redis"],
                ),
                mock.ANY,
                mock.ANY,
            )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "clickhouse",
                "redis",
                "-d",
            ],
            mock.ANY,
        )

        mock_get_container_names_for_project.assert_called_once()

        mock_create_devservices_network.assert_called_once()

        mock_get_non_remote_services.assert_has_calls(
            [
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
            ]
        )

        mock_update_service_entry.assert_has_calls(
            [
                mock.call("example-service", "default", StateTables.STARTING_SERVICES),
                mock.call("example-service", "default", StateTables.STARTED_SERVICES),
            ]
        )
        mock_remove_service_entry.assert_called_once_with(
            "example-service", StateTables.STARTING_SERVICES
        )

        mock_check_all_containers_healthy.assert_called_once()
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'default'" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
@mock.patch("devservices.utils.docker_compose.get_non_remote_services")
def test_up_dependency_error(
    mock_get_non_remote_services: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch(
        "devservices.commands.up.install_and_verify_dependencies",
    ) as mock_install_and_verify_dependencies:
        mock_install_and_verify_dependencies.side_effect = DependencyError(
            "example-repo", "link", "branch"
        )
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        create_config_file(tmp_path, config)
        os.chdir(tmp_path)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=False
        )

        with pytest.raises(SystemExit):
            up(args)

        mock_create_devservices_network.assert_not_called()
        mock_check_all_containers_healthy.assert_not_called()
        # Capture the printed output
        captured = capsys.readouterr()

        assert "DependencyError: example-repo (link) on branch" in captured.out.strip()

        mock_update_service_entry.assert_not_called()
        mock_remove_service_entry.assert_not_called()

        mock_get_non_remote_services.assert_not_called()

        captured = capsys.readouterr()
        assert "Retrieving dependencies" not in captured.out.strip()
        assert (
            "Starting 'example-service' in mode: 'default'" not in captured.out.strip()
        )
        assert "Starting clickhouse" not in captured.out.strip()
        assert "Starting redis" not in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
def test_up_no_config_file(
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False, exclude_local=False)

    with pytest.raises(SystemExit):
        up(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices up sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )

    mock_update_service_entry.assert_not_called()
    mock_remove_service_entry.assert_not_called()


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
@mock.patch(
    "devservices.commands.up.subprocess.check_output",
    side_effect=[
        subprocess.CalledProcessError(
            returncode=1, output="", stderr="Docker Compose error", cmd=""
        ),
    ],
)
def test_up_error(
    mock_subprocess_check_output: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "redis": {"description": "Redis"},
                "clickhouse": {"description": "Clickhouse"},
            },
            "modes": {"default": ["redis", "clickhouse"]},
        },
        "services": {
            "redis": {"image": "redis:6.2.14-alpine"},
            "clickhouse": {
                "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
            },
        },
    }

    create_config_file(tmp_path, config)
    os.chdir(tmp_path)

    args = Namespace(
        service_name=None, debug=False, mode="default", exclude_local=False
    )

    with pytest.raises(SystemExit):
        up(args)

    mock_subprocess_check_output.assert_called_once_with(
        [
            "docker",
            "compose",
            "-f",
            f"{tmp_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
            "config",
            "--services",
        ],
        text=True,
        env=mock.ANY,
    )

    mock_create_devservices_network.assert_called_once()
    mock_check_all_containers_healthy.assert_not_called()
    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to start example-service: Docker Compose error" in captured.out.strip()
    )

    mock_update_service_entry.assert_called_once_with(
        "example-service", "default", StateTables.STARTING_SERVICES
    )
    mock_remove_service_entry.assert_not_called()

    assert "Retrieving dependencies" in captured.out.strip()
    assert "Starting 'example-service' in mode: 'default'" in captured.out.strip()
    assert "Starting clickhouse" not in captured.out.strip()
    assert "Starting redis" not in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
@mock.patch(
    "devservices.utils.docker_compose.get_non_remote_services",
    return_value={"clickhouse", "redis"},
)
def test_up_docker_compose_container_lookup_error(
    mock_get_non_remote_services: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=False
        )

        with (
            pytest.raises(SystemExit),
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                side_effect=DockerComposeError(
                    command=f"docker compose -p example-service -f {service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME} ps --format {{.Name}}",
                    returncode=1,
                    stderr="Error",
                    stdout="",
                ),
            ) as mock_get_container_names_for_project,
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "clickhouse",
                    "redis",
                ],
                project_name="example-service",
                config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["clickhouse", "redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "clickhouse",
                "redis",
                "-d",
            ],
            mock.ANY,
        )

        mock_get_container_names_for_project.assert_called_once()

        mock_create_devservices_network.assert_called_once()

        mock_get_non_remote_services.assert_has_calls(
            [
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
            ]
        )

        mock_update_service_entry.assert_called_once_with(
            "example-service", "default", StateTables.STARTING_SERVICES
        )
        mock_remove_service_entry.assert_not_called()

        mock_check_all_containers_healthy.assert_not_called()
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'default'" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()
        assert (
            "Failed to get containers to healthcheck for example-service"
            in captured.out.strip()
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch(
    "devservices.commands.up.check_all_containers_healthy",
    side_effect=ContainerHealthcheckFailedError("container1", HEALTHCHECK_TIMEOUT),
)
@mock.patch(
    "devservices.utils.docker_compose.get_non_remote_services",
    return_value={"clickhouse", "redis"},
)
def test_up_docker_compose_container_healthcheck_failed(
    mock_get_non_remote_services: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=False
        )

        with (
            pytest.raises(SystemExit),
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                return_value=["container1", "container2"],
            ) as mock_get_container_names_for_project,
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "clickhouse",
                    "redis",
                ],
                project_name="example-service",
                config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["clickhouse", "redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "clickhouse",
                "redis",
                "-d",
            ],
            mock.ANY,
        )

        mock_get_container_names_for_project.assert_called_once()

        mock_create_devservices_network.assert_called_once()

        mock_get_non_remote_services.assert_has_calls(
            [
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
            ]
        )

        mock_update_service_entry.assert_called_once_with(
            "example-service", "default", StateTables.STARTING_SERVICES
        )
        mock_remove_service_entry.assert_not_called()

        mock_check_all_containers_healthy.assert_called_once()
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'default'" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()
        assert (
            "Container container1 did not become healthy within 120 seconds."
            in captured.out.strip()
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up._create_devservices_network")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
@mock.patch(
    "devservices.utils.docker_compose.get_non_remote_services",
    return_value={"clickhouse", "redis"},
)
def test_up_mode_simple(
    mock_get_non_remote_services: mock.Mock,
    mock_check_all_containers_healthy: mock.Mock,
    mock_create_devservices_network: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
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

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(
            service_name=None, debug=False, mode="test", exclude_local=False
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                return_value=["container1", "container2"],
            ) as mock_get_container_names_for_project,
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "redis",
                ],
                project_name="example-service",
                config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "redis",
                "-d",
            ],
            mock.ANY,
        )

        mock_get_container_names_for_project.assert_called_once()

        mock_create_devservices_network.assert_called_once()

        mock_get_non_remote_services.assert_has_calls(
            [
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
                mock.call(
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    mock.ANY,
                ),
            ]
        )

        mock_update_service_entry.assert_has_calls(
            [
                mock.call("example-service", "test", StateTables.STARTING_SERVICES),
                mock.call("example-service", "test", StateTables.STARTED_SERVICES),
            ]
        )
        mock_remove_service_entry.assert_called_once_with(
            "example-service", StateTables.STARTING_SERVICES
        )
        mock_check_all_containers_healthy.assert_called_once()
        captured = capsys.readouterr()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
@mock.patch("devservices.utils.state.State.update_service_entry")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
def test_up_mode_does_not_exist(
    mock_check_all_containers_healthy: mock.Mock,
    mock_update_service_entry: mock.Mock,
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
        str(tmp_path / "dependency-dir"),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        args = Namespace(
            service_name=None, debug=False, mode="test", exclude_local=False
        )

        with (
            pytest.raises(SystemExit),
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.utils.state.State.get_service_entries",
                return_value=["example-service"],
            ),
        ):
            up(args)

        mock_pull_dependency_images.assert_not_called()

        mock_run_cmd.assert_not_called()

        # Capture the printed output
        captured = capsys.readouterr()

        assert (
            "ModeDoesNotExistError: Mode 'test' does not exist for service 'example-service'.\nAvailable modes: default"
            in captured.out.strip()
        )

        mock_update_service_entry.assert_not_called()
        mock_remove_service_entry.assert_not_called()

        mock_check_all_containers_healthy.assert_not_called()

        captured = capsys.readouterr()
        assert "Retrieving dependencies" not in captured.out.strip()
        assert "Starting 'example-service' in mode: 'test'" not in captured.out.strip()
        assert "Starting clickhouse" not in captured.out.strip()
        assert "Starting redis" not in captured.out.strip()


@mock.patch("devservices.commands.up.check_all_containers_healthy")
def test_up_multiple_modes(
    mock_check_all_containers_healthy: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
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

        service_path = tmp_path / "example-service"
        create_config_file(service_path, config)
        os.chdir(service_path)

        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )

        args = Namespace(
            service_name=None, debug=False, mode="test", exclude_local=False
        )
        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                return_value=["container1", "container2"],
            ),
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "redis",
                ],
                project_name="example-service",
                config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "redis",
                "-d",
            ],
            mock.ANY,
        )

        mock_check_all_containers_healthy.assert_called_once()

        captured = capsys.readouterr()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting redis" in captured.out.strip()


@mock.patch("devservices.commands.up.check_all_containers_healthy")
def test_up_multiple_modes_overlapping_running_service(
    mock_check_all_containers_healthy: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        redis_repo_path = tmp_path / "redis"
        create_mock_git_repo("blank_repo", redis_repo_path)
        mock_redis_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "shared-redis",
                "dependencies": {},
                "modes": {"default": []},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(redis_repo_path, mock_redis_config)
        run_git_command(["add", "."], cwd=redis_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=redis_repo_path)
        config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "example-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"], "test": ["clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["redis"]},
            },
        }

        service_path = tmp_path / "code" / "example-service"
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(service_path, config)
        create_config_file(other_service_path, other_config)
        os.chdir(service_path)

        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )

        args = Namespace(
            service_name="example-service",
            debug=False,
            mode="test",
            exclude_local=False,
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.commands.up.get_container_names_for_project",
                return_value=["container1", "container2"],
            ),
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "clickhouse",
                ],
                project_name="example-service",
                config_path=f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["clickhouse"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "up",
                "clickhouse",
                "-d",
            ],
            mock.ANY,
        )

        mock_check_all_containers_healthy.assert_called_once_with(
            mock.ANY,
            ["container1", "container2"],
        )

        captured = capsys.readouterr()
        assert "Starting 'example-service' in mode: 'test'" in captured.out.strip()
        assert "Retrieving dependencies" in captured.out.strip()
        assert "Starting clickhouse" in captured.out.strip()


@mock.patch("devservices.commands.up.find_matching_service")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
def test_up_config_error(
    mock_check_all_containers_healthy: mock.Mock,
    find_matching_service_mock: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    find_matching_service_mock.side_effect = ConfigError("Config error")
    args = Namespace(
        service_name="example-service", debug=False, mode="test", exclude_local=False
    )

    with pytest.raises(SystemExit):
        up(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    mock_check_all_containers_healthy.assert_not_called()
    captured = capsys.readouterr()
    assert "Config error" in captured.out.strip()


@mock.patch("devservices.commands.up.find_matching_service")
@mock.patch("devservices.commands.up.check_all_containers_healthy")
def test_up_service_not_found_error(
    mock_check_all_containers_healthy: mock.Mock,
    find_matching_service_mock: mock.Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    find_matching_service_mock.side_effect = ServiceNotFoundError("Service not found")
    args = Namespace(
        service_name="example-service", debug=False, mode="test", exclude_local=False
    )

    with pytest.raises(SystemExit):
        up(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    mock_check_all_containers_healthy.assert_not_called()
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()


@mock.patch("devservices.utils.state.State.update_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_up_dependency_set_to_local(
    mock_update_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    exclude_local: bool,
) -> None:
    """
    Test that depending on the exclude_local flag, we will not bring up a dependency if it is set to LOCAL runtime.
    """
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        redis_repo_path = create_mock_git_repo("blank_repo", tmp_path / "redis")
        redis_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "redis",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(redis_repo_path, redis_config)
        run_git_command(["add", "."], cwd=redis_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=redis_repo_path)

        local_runtime_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "local-runtime-service"
        )
        local_runtime_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "local-runtime-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        create_config_file(local_runtime_repo_path, local_runtime_config)
        run_git_command(["add", "."], cwd=local_runtime_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=local_runtime_repo_path
        )

        local_runtime_service_path = tmp_path / "code" / "local-runtime-service"
        create_config_file(local_runtime_service_path, local_runtime_config)

        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "local-runtime-service": {
                        "description": "Local runtime service",
                        "remote": {
                            "repo_name": "local-runtime-service",
                            "branch": "main",
                            "repo_link": f"file://{local_runtime_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["redis", "local-runtime-service"]},
            },
        }
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(other_service_path, other_config)

        os.chdir(other_service_path)

        state = State()
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=exclude_local
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up._bring_up_dependency",
            ) as mock_bring_up_dependency,
        ):
            up(args)

        if exclude_local:
            mock_pull_dependency_images.assert_called_once_with(
                DockerComposeCommand(
                    full_command=[
                        "docker",
                        "compose",
                        "-p",
                        "redis",
                        "-f",
                        f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "pull",
                        "redis",
                    ],
                    project_name="redis",
                    config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["redis"],
                ),
                mock.ANY,
                mock.ANY,
            )
        else:
            mock_pull_dependency_images.assert_has_calls(
                [
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "redis",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "pull",
                                "redis",
                            ],
                            project_name="redis",
                            config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "local-runtime-service",
                                "-f",
                                f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "pull",
                                "clickhouse",
                            ],
                            project_name="local-runtime-service",
                            config_path=f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["clickhouse"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "redis",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "pull",
                                "redis",
                            ],
                            project_name="redis",
                            config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        if exclude_local:
            # local-runtime-service is not started since it is set to runtime LOCAL
            # this means it should be brought up separately by the user
            mock_bring_up_dependency.assert_called_once_with(
                DockerComposeCommand(
                    full_command=[
                        "docker",
                        "compose",
                        "-p",
                        "redis",
                        "-f",
                        f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "up",
                        "redis",
                        "-d",
                    ],
                    project_name="redis",
                    config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["redis"],
                ),
                mock.ANY,
                mock.ANY,
            )
        else:
            mock_bring_up_dependency.assert_has_calls(
                [
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "redis",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "up",
                                "redis",
                                "-d",
                            ],
                            project_name="redis",
                            config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "local-runtime-service",
                                "-f",
                                f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "up",
                                "clickhouse",
                                "-d",
                            ],
                            project_name="local-runtime-service",
                            config_path=f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["clickhouse"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "redis",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "up",
                                "redis",
                                "-d",
                            ],
                            project_name="redis",
                            config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        if exclude_local:
            mock_update_service_entry.assert_has_calls(
                [
                    mock.call(
                        "other-service", "default", StateTables.STARTING_SERVICES
                    ),
                    mock.call("other-service", "default", StateTables.STARTED_SERVICES),
                ]
            )
        else:
            mock_update_service_entry.assert_has_calls(
                [
                    mock.call(
                        "other-service", "default", StateTables.STARTING_SERVICES
                    ),
                    mock.call(
                        "local-runtime-service",
                        "default",
                        StateTables.STARTING_SERVICES,
                    ),
                    mock.call(
                        "local-runtime-service", "default", StateTables.STARTED_SERVICES
                    ),
                    mock.call("other-service", "default", StateTables.STARTED_SERVICES),
                ]
            )

        captured = capsys.readouterr()
        if exclude_local:
            assert (
                captured.out.strip().count(
                    "Skipping 'local-runtime-service' as it is set to run locally"
                )
                == 1
            )
        else:
            assert (
                captured.out.strip().count(
                    "Skipping 'local-runtime-service' as it is set to run locally"
                )
                == 0
            )


@mock.patch("devservices.utils.state.State.update_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_up_nested_dependency_set_to_local(
    mock_update_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    exclude_local: bool,
) -> None:
    """
    Test that depending on the exclude_local flag, we either bring up a nested dependency or not that has a local runtime.
    """
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        local_runtime_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "local-runtime-service"
        )
        local_runtime_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "local-runtime-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(local_runtime_repo_path, local_runtime_config)
        run_git_command(["add", "."], cwd=local_runtime_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=local_runtime_repo_path
        )

        local_runtime_service_path = tmp_path / "code" / "local-runtime-service"
        create_config_file(local_runtime_service_path, local_runtime_config)

        child_service_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "child-service"
        )
        child_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "child-service",
                "dependencies": {
                    "local-runtime-service": {
                        "description": "local-runtime-service",
                        "remote": {
                            "repo_name": "local-runtime-service",
                            "branch": "main",
                            "repo_link": f"file://{local_runtime_repo_path}",
                        },
                    },
                    "child-service": {"description": "child-service"},
                },
                "modes": {"default": ["local-runtime-service", "child-service"]},
            },
            "services": {
                "child-service": {"image": "child-service:latest"},
            },
        }
        create_config_file(child_service_repo_path, child_config)
        run_git_command(["add", "."], cwd=child_service_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=child_service_repo_path
        )

        child_service_path = tmp_path / "code" / "child-service"
        create_config_file(child_service_path, child_config)

        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "child-service": {
                        "description": "child-service",
                        "remote": {
                            "repo_name": "child-service",
                            "branch": "main",
                            "repo_link": f"file://{child_service_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["child-service"]},
            },
            "services": {
                "other-service": {"image": "other-service:latest"},
            },
        }
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(other_service_path, other_config)

        os.chdir(other_service_path)

        state = State()
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=exclude_local
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up._bring_up_dependency",
            ) as mock_bring_up_dependency,
        ):
            up(args)

        if exclude_local:
            mock_pull_dependency_images.assert_called_once_with(
                DockerComposeCommand(
                    full_command=[
                        "docker",
                        "compose",
                        "-p",
                        "child-service",
                        "-f",
                        f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "pull",
                        "child-service",
                    ],
                    project_name="child-service",
                    config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["child-service"],
                ),
                mock.ANY,
                mock.ANY,
            )
        else:
            mock_pull_dependency_images.assert_has_calls(
                [
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "local-runtime-service",
                                "-f",
                                f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "pull",
                                "redis",
                            ],
                            project_name="local-runtime-service",
                            config_path=f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "child-service",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "pull",
                                "child-service",
                            ],
                            project_name="child-service",
                            config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["child-service"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        if exclude_local:
            # local-runtime-service is not started since it is set to runtime LOCAL
            # this means it should be brought up separately by the user
            mock_bring_up_dependency.assert_called_once_with(
                DockerComposeCommand(
                    full_command=[
                        "docker",
                        "compose",
                        "-p",
                        "child-service",
                        "-f",
                        f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                        "up",
                        "child-service",
                        "-d",
                    ],
                    project_name="child-service",
                    config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["child-service"],
                ),
                mock.ANY,
                mock.ANY,
            )
        else:
            mock_bring_up_dependency.assert_has_calls(
                [
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "local-runtime-service",
                                "-f",
                                f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "up",
                                "redis",
                                "-d",
                            ],
                            project_name="local-runtime-service",
                            config_path=f"{tmp_path}/code/local-runtime-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["redis"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "child-service",
                                "-f",
                                f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "up",
                                "child-service",
                                "-d",
                            ],
                            project_name="child-service",
                            config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["child-service"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        if exclude_local:
            mock_update_service_entry.assert_has_calls(
                [
                    mock.call(
                        "other-service", "default", StateTables.STARTING_SERVICES
                    ),
                    mock.call("other-service", "default", StateTables.STARTED_SERVICES),
                ]
            )
        else:
            mock_update_service_entry.assert_has_calls(
                [
                    mock.call(
                        "other-service", "default", StateTables.STARTING_SERVICES
                    ),
                    mock.call(
                        "local-runtime-service",
                        "default",
                        StateTables.STARTING_SERVICES,
                    ),
                    mock.call(
                        "local-runtime-service", "default", StateTables.STARTED_SERVICES
                    ),
                    mock.call("other-service", "default", StateTables.STARTED_SERVICES),
                ]
            )

        captured = capsys.readouterr()
        if exclude_local:
            assert (
                captured.out.strip().count(
                    "Skipping 'local-runtime-service' as it is set to run locally"
                )
                == 1
            )
        else:
            assert (
                captured.out.strip().count(
                    "Skipping 'local-runtime-service' as it is set to run locally"
                )
                == 0
            )


@mock.patch("devservices.utils.state.State.update_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_up_does_not_bring_up_nested_dependency_if_set_to_local_and_mode_does_not_contain_it(
    mock_update_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    exclude_local: bool,
) -> None:
    """
    Test that we do not bring up a nested dependency if it is set to LOCAL runtime and assuming the mode does not contain it,
    it should NOT write a warning to the console, no matter if exclude_local is True or False.
    """
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        local_runtime_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "local-runtime-service"
        )
        local_runtime_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "local-runtime-service",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(local_runtime_repo_path, local_runtime_config)
        run_git_command(["add", "."], cwd=local_runtime_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=local_runtime_repo_path
        )

        child_service_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "child-service"
        )
        child_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "child-service",
                "dependencies": {
                    "local-runtime-service": {
                        "description": "local-runtime-service",
                        "remote": {
                            "repo_name": "local-runtime-service",
                            "branch": "main",
                            "repo_link": f"file://{local_runtime_repo_path}",
                        },
                    },
                    "child-service": {"description": "child-service"},
                },
                "modes": {
                    "default": ["child-service"],
                    "other": ["local-runtime-service"],
                },
            },
            "services": {
                "child-service": {"image": "child-service:latest"},
            },
        }
        create_config_file(child_service_repo_path, child_config)
        run_git_command(["add", "."], cwd=child_service_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=child_service_repo_path
        )

        child_service_path = tmp_path / "code" / "child-service"
        create_config_file(child_service_path, child_config)

        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "child-service": {
                        "description": "child-service",
                        "remote": {
                            "repo_name": "child-service",
                            "branch": "main",
                            "repo_link": f"file://{child_service_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["child-service"]},
            },
            "services": {
                "other-service": {"image": "other-service:latest"},
            },
        }
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(other_service_path, other_config)

        os.chdir(other_service_path)

        state = State()
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=exclude_local
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up._bring_up_dependency",
            ) as mock_bring_up_dependency,
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "child-service",
                    "-f",
                    f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "child-service",
                ],
                project_name="child-service",
                config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["child-service"],
            ),
            mock.ANY,
            mock.ANY,
        )

        # local-runtime-service is not started since it is set to runtime LOCAL
        # this means it should be brought up separately by the user
        mock_bring_up_dependency.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "child-service",
                    "-f",
                    f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "up",
                    "child-service",
                    "-d",
                ],
                project_name="child-service",
                config_path=f"{tmp_path}/dependency-dir/v1/child-service/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["child-service"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_update_service_entry.assert_has_calls(
            [
                mock.call("other-service", "default", StateTables.STARTING_SERVICES),
                mock.call("other-service", "default", StateTables.STARTED_SERVICES),
            ]
        )

        captured = capsys.readouterr()
        assert (
            captured.out.strip().count(
                "Skipping 'local-runtime-service' as it is set to run locally"
            )
            == 0
        )


@mock.patch("devservices.utils.state.State.update_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_up_does_not_bring_up_dependency_if_set_to_local_and_mode_does_not_contain_it(
    mock_update_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    exclude_local: bool,
) -> None:
    """
    Test that we do not bring up a dependency if it is set to LOCAL runtime especially if the mode does not contain it,
    and assuming the mode does not contain it, it should NOT write a warning to the console, no matter if exclude_local is True or False.
    """
    with (
        mock.patch(
            "devservices.commands.up.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.dependencies.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        redis_repo_path = create_mock_git_repo("blank_repo", tmp_path / "redis")
        redis_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "redis",
                "dependencies": {
                    "redis": {"description": "Redis"},
                },
                "modes": {"default": ["redis"]},
            },
            "services": {
                "redis": {"image": "redis:6.2.14-alpine"},
            },
        }
        create_config_file(redis_repo_path, redis_config)
        run_git_command(["add", "."], cwd=redis_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=redis_repo_path)

        local_runtime_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "local-runtime-service"
        )
        local_runtime_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "local-runtime-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        create_config_file(local_runtime_repo_path, local_runtime_config)
        run_git_command(["add", "."], cwd=local_runtime_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=local_runtime_repo_path
        )

        local_runtime_service_path = tmp_path / "code" / "local-runtime-service"
        create_config_file(local_runtime_service_path, local_runtime_config)

        other_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "other-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "local-runtime-service": {
                        "description": "Local runtime service",
                        "remote": {
                            "repo_name": "local-runtime-service",
                            "branch": "main",
                            "repo_link": f"file://{local_runtime_repo_path}",
                        },
                    },
                },
                "modes": {
                    "default": ["redis"],
                    "other-mode": ["local-runtime-service"],
                },
            },
        }
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(other_service_path, other_config)

        os.chdir(other_service_path)

        state = State()
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(
            service_name=None, debug=False, mode="default", exclude_local=exclude_local
        )

        with (
            mock.patch(
                "devservices.commands.up._pull_dependency_images",
            ) as mock_pull_dependency_images,
            mock.patch(
                "devservices.commands.up._bring_up_dependency",
            ) as mock_bring_up_dependency,
        ):
            up(args)

        mock_pull_dependency_images.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "redis",
                    "-f",
                    f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "pull",
                    "redis",
                ],
                project_name="redis",
                config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        # local-runtime-service is not started since not only is it not in the mode, it is also set to runtime LOCAL
        # which means it would be brought up separately by the user
        mock_bring_up_dependency.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "redis",
                    "-f",
                    f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "up",
                    "redis",
                    "-d",
                ],
                project_name="redis",
                config_path=f"{tmp_path}/dependency-dir/v1/redis/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["redis"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_update_service_entry.assert_has_calls(
            [
                mock.call("other-service", "default", StateTables.STARTING_SERVICES),
                mock.call("other-service", "default", StateTables.STARTED_SERVICES),
            ]
        )

        captured = capsys.readouterr()
        assert (
            captured.out.strip().count(
                "Skipping 'local-runtime-service' as it is set to run locally"
            )
            == 0
        )
