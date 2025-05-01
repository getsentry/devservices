from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.down import down
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_starting(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with (
            mock.patch(
                "devservices.commands.down.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")
            ),
        ):
            state = State()
            state.update_service_entry(
                "example-service", "default", StateTables.STARTING_SERVICES
            )
            down(args)

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "stop",
                "clickhouse",
                "redis",
            ],
            mock.ANY,
        )

        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )

        captured = capsys.readouterr()
        assert "Stopping clickhouse" in captured.out.strip()
        assert "Stopping redis" in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_started(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with (
            mock.patch(
                "devservices.commands.down.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="clickhouse\nredis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")
            ),
        ):
            state = State()
            state.update_service_entry(
                "example-service", "default", StateTables.STARTED_SERVICES
            )
            down(args)

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "stop",
                "clickhouse",
                "redis",
            ],
            mock.ANY,
        )

        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )

        captured = capsys.readouterr()
        assert "Stopping clickhouse" in captured.out.strip()
        assert "Stopping redis" in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_no_config_file(
    mock_remove_service_entry: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    os.chdir(tmp_path)

    args = Namespace(service_name=None, debug=False, exclude_local=False)

    with pytest.raises(SystemExit):
        down(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        f"No devservices configuration found in {tmp_path}/devservices/config.yml. Please specify a service (i.e. `devservices down sentry`) or run the command from a directory with a devservices configuration."
        in captured.out.strip()
    )

    mock_remove_service_entry.assert_not_called()


@mock.patch("devservices.utils.docker_compose.subprocess.run")
@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_error(
    mock_remove_service_entry: mock.Mock,
    mock_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, stderr="Docker Compose error", cmd=""
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

    args = Namespace(service_name=None, debug=False, exclude_local=False)

    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        pytest.raises(SystemExit),
    ):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        down(args)

    # Capture the printed output
    captured = capsys.readouterr()

    assert (
        "Failed to stop example-service: Docker Compose error" in captured.out.strip()
    )

    mock_remove_service_entry.assert_not_called()

    assert "Stopping clickhouse" not in captured.out.strip()
    assert "Stopping redis" not in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_mode_simple(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch(
        "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with (
            mock.patch(
                "devservices.commands.down.run_cmd",
                return_value=subprocess.CompletedProcess(
                    args=["docker", "compose", "config", "--services"],
                    returncode=0,
                    stdout="redis\n",
                ),
            ) as mock_run_cmd,
            mock.patch(
                "devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")
            ),
        ):
            state = State()
            state.update_service_entry(
                "example-service", "test", StateTables.STARTED_SERVICES
            )
            down(args)

        mock_run_cmd.assert_called_once_with(
            [
                "docker",
                "compose",
                "-p",
                "example-service",
                "-f",
                f"{service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                "stop",
                "redis",
            ],
            mock.ANY,
        )

        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )

        captured = capsys.readouterr()
        assert "Stopping redis" in captured.out.strip()


@mock.patch("devservices.commands.down.find_matching_service")
def test_down_config_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ConfigError("Config error")
    args = Namespace(service_name="example-service", debug=False, exclude_local=False)

    with pytest.raises(SystemExit):
        down(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Config error" in captured.out.strip()


@mock.patch("devservices.commands.down.find_matching_service")
def test_down_service_not_found_error(
    find_matching_service_mock: mock.Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    find_matching_service_mock.side_effect = ServiceNotFoundError("Service not found")
    args = Namespace(service_name="example-service", debug=False, exclude_local=False)

    with pytest.raises(SystemExit):
        down(args)

    find_matching_service_mock.assert_called_once_with("example-service")
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_overlapping_services(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
) -> None:
    """
    Test that the down command doesn't stop shared dependencies that are being used by
    another service.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        example_service_path = tmp_path / "code" / "example-service"
        other_service_path = tmp_path / "code" / "other-service"
        create_config_file(example_service_path, example_config)
        create_config_file(other_service_path, other_config)

        os.chdir(example_service_path)

        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with mock.patch(
            "devservices.commands.down._bring_down_dependency"
        ) as mock_bring_down_dependency:
            down(args)

            # Shouldn't stop redis because other-service is using it
            mock_bring_down_dependency.assert_has_calls(
                [
                    mock.call(
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
                            config_path=f"{example_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["clickhouse"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        # example-service should be stopped
        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_does_not_stop_service_being_used_by_another_service(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
) -> None:
    """
    Test that the down command doesn't stop services that are being used by another service
    even if the service is being run explicitly.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with mock.patch(
            "devservices.commands.down._bring_down_dependency"
        ) as mock_bring_down_dependency:
            down(args)

            # Shouldn't bring down anything since example-service is being used by other-service
            mock_bring_down_dependency.assert_not_called()

        # example-service should be stopped
        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_does_not_stop_nested_service_being_used_by_another_service(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
) -> None:
    """
    Test that the down command doesn't stop services that are being used by another service
    even if the service is being run explicitly where the service being stopped is nested dependency of another service
    that is not being run explicitly but instead is a dependency of another service being run.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        child_repo_path = create_mock_git_repo("blank_repo", tmp_path / "child-service")
        child_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "child-service",
                "dependencies": {
                    "clickhouse": {"description": "Clickhouse"},
                },
                "modes": {"default": ["clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }
        create_config_file(child_repo_path, child_config)
        run_git_command(["add", "."], cwd=child_repo_path)
        run_git_command(["commit", "-m", "Add devservices config"], cwd=child_repo_path)

        child_service_path = tmp_path / "code" / "child-service"
        create_config_file(child_service_path, child_config)

        parent_repo_path = create_mock_git_repo(
            "blank_repo", tmp_path / "parent-service"
        )
        parent_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "parent-service",
                "dependencies": {
                    "redis": {
                        "description": "Redis",
                        "remote": {
                            "repo_name": "redis",
                            "branch": "main",
                            "repo_link": f"file://{redis_repo_path}",
                        },
                    },
                    "child-service": {
                        "description": "Child service",
                        "remote": {
                            "repo_name": "child-service",
                            "branch": "main",
                            "repo_link": f"file://{child_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["redis", "child-service"]},
            },
        }
        create_config_file(parent_repo_path, parent_config)
        run_git_command(["add", "."], cwd=parent_repo_path)
        run_git_command(
            ["commit", "-m", "Add devservices config"], cwd=parent_repo_path
        )

        grandparent_config = {
            "x-sentry-service-config": {
                "version": 0.1,
                "service_name": "grandparent-service",
                "dependencies": {
                    "parent-service": {
                        "description": "Parent service",
                        "remote": {
                            "repo_name": "parent-service",
                            "branch": "main",
                            "repo_link": f"file://{parent_repo_path}",
                        },
                    },
                },
                "modes": {"default": ["parent-service"]},
            },
        }

        grandparent_service_path = tmp_path / "code" / "other-service"
        create_config_file(grandparent_service_path, grandparent_config)

        install_and_verify_dependencies(
            Service(
                name="grandparent-service",
                repo_path=str(grandparent_service_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="grandparent-service",
                    dependencies={
                        "parent-service": Dependency(
                            description="Parent service",
                            remote=RemoteConfig(
                                repo_name="parent-service",
                                repo_link=f"file://{parent_repo_path}",
                                branch="main",
                                mode="default",
                            ),
                        ),
                    },
                    modes={"default": ["parent-service"]},
                ),
            )
        )

        os.chdir(child_service_path)

        state = State()
        state.update_service_entry(
            "child-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "grandparent-service", "default", StateTables.STARTED_SERVICES
        )

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with mock.patch(
            "devservices.commands.down._bring_down_dependency"
        ) as mock_bring_down_dependency:
            down(args)

            # Shouldn't bring down anything since child-service is being used by parent-service which is being used by grandparent-service
            mock_bring_down_dependency.assert_not_called()

        # child-service should be stopped
        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("child-service", StateTables.STARTING_SERVICES),
                mock.call("child-service", StateTables.STARTED_SERVICES),
            ]
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
def test_down_overlapping_non_remote_services(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
) -> None:
    """
    Test that the down command stops services that are shared between two running services
    when the shared service is technically not a remote dependency in one of the services.
    This happens in the case where the shared service is itself being run, meaning it is
    local to itself.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        redis_service_path = tmp_path / "code" / "redis"
        create_config_file(redis_service_path, redis_config)

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
                "modes": {"default": ["redis", "clickhouse"], "test": ["clickhouse"]},
            },
            "services": {
                "clickhouse": {
                    "image": "altinity/clickhouse-server:23.8.11.29.altinitystable"
                },
            },
        }

        example_service_path = tmp_path / "code" / "example-service"
        create_config_file(example_service_path, example_config)
        os.chdir(example_service_path)

        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry("redis", "default", StateTables.STARTED_SERVICES)

        args = Namespace(service_name=None, debug=False, exclude_local=False)

        with mock.patch(
            "devservices.commands.down._bring_down_dependency"
        ) as mock_bring_down_dependency:
            down(args)

            # Shouldn't stop redis it's being used by itself
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
                    config_path=f"{example_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    services=["clickhouse"],
                ),
                mock.ANY,
                mock.ANY,
            )

        # example-service should be stopped
        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("example-service", StateTables.STARTING_SERVICES),
                mock.call("example-service", StateTables.STARTED_SERVICES),
            ]
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_down_local_service_with_dependent_service_running(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that based on the exclude_local flag, the down command will bring down
    a service that is set to local runtime, even if a service that depends on it is running.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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
                        "description": "Example service",
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

        os.chdir(local_runtime_service_path)

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
                        "local-runtime-service": Dependency(
                            description="Local runtime service",
                            remote=RemoteConfig(
                                repo_name="local-runtime-service",
                                repo_link=f"file://{local_runtime_repo_path}",
                                branch="main",
                                mode="default",
                            ),
                        ),
                    },
                    modes={"default": ["redis", "local-runtime-service"]},
                ),
            )
        )

        state = State()
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "local-runtime-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(service_name=None, debug=False, exclude_local=exclude_local)

        with (
            mock.patch(
                "devservices.commands.down._bring_down_dependency",
            ) as mock_bring_down_dependency,
        ):
            down(args)

        # local-runtime-service is able to be brought down even though it is set to runtime LOCAL
        # but does not bring redis down since it is being used by other-service
        mock_bring_down_dependency.assert_called_once_with(
            DockerComposeCommand(
                full_command=[
                    "docker",
                    "compose",
                    "-p",
                    "local-runtime-service",
                    "-f",
                    f"{local_runtime_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                    "stop",
                    "clickhouse",
                ],
                project_name="local-runtime-service",
                config_path=f"{local_runtime_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                services=["clickhouse"],
            ),
            mock.ANY,
            mock.ANY,
        )

        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("local-runtime-service", StateTables.STARTING_SERVICES),
                mock.call("local-runtime-service", StateTables.STARTED_SERVICES),
            ]
        )


@mock.patch("devservices.utils.state.State.remove_service_entry")
@pytest.mark.parametrize("exclude_local", [True, False])
def test_down_shared_and_local_dependencies(
    mock_remove_service_entry: mock.Mock,
    tmp_path: Path,
    exclude_local: bool,
) -> None:
    """
    Test that based on the exclude_local flag, the down command will bring down
    either all dependencies, or none in the case that there is a local dependency
    as well as a remote shared dependency.
    """
    with (
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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
                        "description": "Example service",
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
        state.update_service_entry(
            "other-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "local-runtime-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_runtime("local-runtime-service", ServiceRuntime.LOCAL)

        args = Namespace(service_name=None, debug=False, exclude_local=exclude_local)

        with (
            mock.patch(
                "devservices.commands.down._bring_down_dependency",
            ) as mock_bring_down_dependency,
        ):
            down(args)

        if exclude_local:
            # local-runtime-service is not brought down since it is set to runtime LOCAL
            # this means it should be brought down separately by the user. Since redis is shared,
            # it won't be brought down either.
            mock_bring_down_dependency.assert_not_called()
        else:
            mock_bring_down_dependency.assert_has_calls(
                [
                    mock.call(
                        DockerComposeCommand(
                            full_command=[
                                "docker",
                                "compose",
                                "-p",
                                "local-runtime-service",
                                "-f",
                                f"{local_runtime_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                                "stop",
                                "clickhouse",
                            ],
                            project_name="local-runtime-service",
                            config_path=f"{local_runtime_service_path}/{DEVSERVICES_DIR_NAME}/{CONFIG_FILE_NAME}",
                            services=["clickhouse"],
                        ),
                        mock.ANY,
                        mock.ANY,
                    ),
                ]
            )

        mock_remove_service_entry.assert_has_calls(
            [
                mock.call("other-service", StateTables.STARTING_SERVICES),
                mock.call("other-service", StateTables.STARTED_SERVICES),
            ]
        )
