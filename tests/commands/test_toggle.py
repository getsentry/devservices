from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.toggle import toggle
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


def test_toggle_nothing_running(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        with mock.patch(
            "devservices.commands.toggle.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        state = State()

        toggle(Namespace(service_name=None, debug=False, runtime="local"))

        assert state.get_service_runtime("example-service") == ServiceRuntime.LOCAL

        captured = capsys.readouterr()

        assert "example-service is now running in local runtime" in captured.out.strip()

        toggle(Namespace(service_name=None, debug=False, runtime="containerized"))

        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )

        captured = capsys.readouterr()

        assert (
            "example-service is now running in containerized runtime"
            in captured.out.strip()
        )


def test_toggle_nothing_running_same_runtime(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        with mock.patch(
            "devservices.commands.toggle.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        state = State()

        toggle(Namespace(service_name=None, debug=False, runtime="containerized"))

        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )

        captured = capsys.readouterr()

        assert (
            "example-service is already running in containerized runtime"
            in captured.out.strip()
        )


@mock.patch("devservices.commands.toggle._bring_down_dependency")
def test_toggle_dependent_service_running(
    mock_bring_down_dependency: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.commands.toggle.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
        ),
        mock.patch(
            "devservices.utils.services.get_coderoot",
            return_value=str(tmp_path / "code"),
        ),
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

        example_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "example-service"
        )
        example_config = {
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
                "modes": {"default": ["redis", "clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        create_config_file(example_repo_path, example_config)
        run_git_command(["add", "."], cwd=example_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=example_repo_path
        )

        example_service_path = tmp_path / "code" / "example-service"
        create_config_file(example_service_path, example_config)

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
                    "example-service": {
                        "description": "Example service",
                        "remote": {
                            "repo_name": "example-service",
                            "branch": "main",
                            "repo_link": f"file://{example_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["redis", "example-service"]},
            },
        }
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(other_service_path, other_config)

        install_and_verify_dependencies(
            Service(
                name="other-service",
                repo_path=str(other_service_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="other-service",
                    dependencies={
                        "redis": Dependency(
                            description="Redis",
                            remote=RemoteConfig(
                                repo_name="redis",
                                repo_link=f"file://{redis_repo_path}",
                                branch="main",
                                mode="default",
                            ),
                        ),
                        "example-service": Dependency(
                            description="Example service",
                            remote=RemoteConfig(
                                repo_name="example-service",
                                repo_link=f"file://{example_repo_path}",
                                branch="main",
                                mode="default",
                            ),
                        ),
                    },
                    modes={"default": ["redis", "example-service"]},
                ),
            )
        )

        os.chdir(example_service_path)

        state = State()
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )

        toggle(Namespace(service_name=None, debug=False, runtime="local"))

        assert state.get_service_runtime("example-service") == ServiceRuntime.LOCAL

        mock_bring_down_dependency.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "example-service",
                    "-f",
                    f"{example_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "stop",
                    "clickhouse",
                ],
                project_name="example-service",
                config_path=str(
                    example_service_path / DEVSERVICES_DIR_NAME / CONFIG_FILE_NAME
                ),
                services=["clickhouse"],
            ),
            mock.ANY,
            mock.ANY,
        )
