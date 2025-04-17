from __future__ import annotations

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest

from devservices.commands.toggle import bring_down_containerized_service
from devservices.commands.toggle import handle_transition_to_containerized_runtime
from devservices.commands.toggle import handle_transition_to_local_runtime
from devservices.commands.toggle import restart_dependent_services
from devservices.commands.toggle import toggle
from devservices.configs.service_config import Dependency
from devservices.configs.service_config import RemoteConfig
from devservices.configs.service_config import ServiceConfig
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import ConfigNotFoundError
from devservices.exceptions import ConfigParseError
from devservices.exceptions import DependencyError
from devservices.exceptions import ServiceNotFoundError
from devservices.utils.dependencies import install_and_verify_dependencies
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.services import Service
from devservices.utils.state import ServiceRuntime
from devservices.utils.state import State
from devservices.utils.state import StateTables
from testing.utils import create_config_file
from testing.utils import create_mock_git_repo
from testing.utils import run_git_command


@mock.patch("devservices.commands.toggle.find_matching_service")
def test_toggle_config_not_found(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_find_matching_service.side_effect = ConfigNotFoundError("Config not found")
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        toggle(
            Namespace(
                service_name=None, debug=False, runtime=ServiceRuntime.LOCAL.value
            )
        )

    mock_find_matching_service.assert_called_once_with(None)
    captured = capsys.readouterr()
    assert "Config not found" in captured.out.strip()


@mock.patch("devservices.commands.toggle.find_matching_service")
def test_toggle_config_error(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_find_matching_service.side_effect = ConfigParseError("Config parse error")
    with (
        pytest.raises(SystemExit),
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        toggle(
            Namespace(
                service_name=None, debug=False, runtime=ServiceRuntime.LOCAL.value
            )
        )

    mock_find_matching_service.assert_called_once_with(None)
    captured = capsys.readouterr()
    assert "Config parse error" in captured.out.strip()


@mock.patch("devservices.commands.toggle.find_matching_service")
def test_toggle_service_not_found(
    mock_find_matching_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_find_matching_service.side_effect = ServiceNotFoundError("Service not found")
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        toggle(
            Namespace(
                service_name=None, debug=False, runtime=ServiceRuntime.LOCAL.value
            )
        )

    mock_find_matching_service.assert_called_once_with(None)
    captured = capsys.readouterr()
    assert "Service not found" in captured.out.strip()


def test_toggle_nothing_running(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
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

        state = State()

        toggle(
            Namespace(
                service_name=None, debug=False, runtime=ServiceRuntime.LOCAL.value
            )
        )

        assert state.get_service_runtime("example-service") == ServiceRuntime.LOCAL

        captured = capsys.readouterr()

        assert (
            f"example-service is now running in {ServiceRuntime.LOCAL.value} runtime"
            in captured.out.strip()
        )

        toggle(
            Namespace(
                service_name=None,
                debug=False,
                runtime=ServiceRuntime.CONTAINERIZED.value,
            )
        )

        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )

        captured = capsys.readouterr()

        assert (
            f"example-service is now running in {ServiceRuntime.CONTAINERIZED.value} runtime"
            in captured.out.strip()
        )


def test_toggle_nothing_running_same_runtime(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
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

        state = State()

        toggle(
            Namespace(
                service_name=None,
                debug=False,
                runtime=ServiceRuntime.CONTAINERIZED.value,
            )
        )

        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )

        captured = capsys.readouterr()

        assert (
            f"example-service is already running in {ServiceRuntime.CONTAINERIZED.value} runtime"
            in captured.out.strip()
        )


@mock.patch("devservices.commands.down._bring_down_dependency")
def test_toggle_dependent_service_running(
    mock_bring_down_dependency: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        toggle(
            Namespace(
                service_name=None, debug=False, runtime=ServiceRuntime.LOCAL.value
            )
        )

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


def test_handle_transition_to_local_runtime_currently_running_standalone(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
    ):
        state = State()
        state.update_service_runtime("example-service", ServiceRuntime.CONTAINERIZED)
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )

        handle_transition_to_local_runtime(
            Service(
                name="example-service",
                repo_path=str(tmp_path / "example-service"),
                config=ServiceConfig(
                    version=0.1,
                    service_name="example-service",
                    dependencies={
                        "clickhouse": Dependency(
                            description="Clickhouse",
                            remote=None,
                        ),
                    },
                    modes={"default": ["clickhouse"]},
                ),
            )
        )

        assert state.get_service_runtime("example-service") == ServiceRuntime.LOCAL

        captured = capsys.readouterr()

        assert (
            f"example-service is now running in {ServiceRuntime.LOCAL.value} runtime"
            in captured.out.strip()
        )


@mock.patch("devservices.commands.toggle.restart_dependent_services")
def test_handle_transition_to_containerized_runtime_no_dependent_services(
    mock_restart_dependent_services: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
            str(tmp_path / "dependency-dir"),
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

        os.chdir(redis_repo_path)

        state = State()
        state.update_service_runtime("redis", ServiceRuntime.LOCAL)

        handle_transition_to_containerized_runtime(
            Service(
                name="redis",
                repo_path=str(redis_repo_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="redis",
                    dependencies={
                        "redis": Dependency(
                            description="Redis",
                            remote=None,
                        ),
                    },
                    modes={"default": ["redis"]},
                ),
            )
        )

        assert state.get_service_runtime("redis") == ServiceRuntime.CONTAINERIZED

        mock_restart_dependent_services.assert_not_called()


def test_handle_transition_to_containerized_runtime_with_service_running(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with (
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

        os.chdir(redis_repo_path)

        state = State()
        state.update_service_runtime("redis", ServiceRuntime.LOCAL)
        state.update_service_entry("redis", "default", StateTables.STARTED_SERVICES)

        handle_transition_to_containerized_runtime(
            Service(
                name="redis",
                repo_path=str(redis_repo_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="redis",
                    dependencies={
                        "redis": Dependency(description="Redis", remote=None),
                    },
                    modes={"default": ["redis"]},
                ),
            )
        )

        assert state.get_service_runtime("redis") != ServiceRuntime.CONTAINERIZED

        captured = capsys.readouterr()

        assert "redis is running, please stop it first" in captured.out.strip()


@mock.patch("devservices.commands.toggle.restart_dependent_services")
def test_handle_transition_to_containerized_runtime_with_dependent_services(
    mock_restart_dependent_services: mock.Mock,
    tmp_path: Path,
) -> None:
    with (
        mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")),
        mock.patch(
            "devservices.commands.down.DEVSERVICES_DEPENDENCIES_CACHE_DIR",
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

        handle_transition_to_containerized_runtime(
            Service(
                name="example-service",
                repo_path=str(example_service_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="example-service",
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
                        "clickhouse": Dependency(
                            description="Clickhouse",
                            remote=None,
                        ),
                    },
                    modes={"default": ["redis", "clickhouse"]},
                ),
            )
        )

        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )
        mock_restart_dependent_services.assert_called_once_with(
            "example-service",
            {"other-service": ["default"]},
        )


@mock.patch("devservices.commands.toggle.subprocess.run")
def test_restart_dependent_services_single_dependent_service_single_mode(
    mock_subprocess_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    restart_dependent_services("example-service", {"dependent-service": ["default"]})

    mock_subprocess_run.assert_called_once_with(
        ["devservices", "up", "dependent-service", "--mode", "default"],
        check=True,
        text=True,
        stdout=mock.ANY,
    )

    captured = capsys.readouterr()

    assert (
        f"Restarting dependent services to ensure example-service is running in a {ServiceRuntime.CONTAINERIZED.value} runtime"
        in captured.out.strip()
    )
    assert "Restarting dependent-service in mode default" in captured.out.strip()


@mock.patch("devservices.commands.toggle.subprocess.run")
def test_restart_dependent_services_single_dependent_service_multiple_modes(
    mock_subprocess_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    restart_dependent_services(
        "example-service", {"dependent-service": ["default", "other-mode"]}
    )

    mock_subprocess_run.assert_has_calls(
        [
            mock.call(
                ["devservices", "up", "dependent-service", "--mode", "default"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
            mock.call(
                ["devservices", "up", "dependent-service", "--mode", "other-mode"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
        ]
    )

    captured = capsys.readouterr()

    assert (
        f"Restarting dependent services to ensure example-service is running in a {ServiceRuntime.CONTAINERIZED.value} runtime"
        in captured.out.strip()
    )
    assert "Restarting dependent-service in mode default" in captured.out.strip()
    assert "Restarting dependent-service in mode other-mode" in captured.out.strip()


@mock.patch("devservices.commands.toggle.subprocess.run")
def test_restart_dependent_services_multiple_dependent_services_single_mode(
    mock_subprocess_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    restart_dependent_services(
        "example-service",
        {"dependent-service": ["default"], "other-dependent-service": ["default"]},
    )

    mock_subprocess_run.assert_has_calls(
        [
            mock.call(
                ["devservices", "up", "dependent-service", "--mode", "default"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
            mock.call(
                ["devservices", "up", "other-dependent-service", "--mode", "default"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
        ]
    )

    captured = capsys.readouterr()

    assert (
        f"Restarting dependent services to ensure example-service is running in a {ServiceRuntime.CONTAINERIZED.value} runtime"
        in captured.out.strip()
    )
    assert "Restarting dependent-service in mode default" in captured.out.strip()
    assert "Restarting other-dependent-service in mode default" in captured.out.strip()


@mock.patch("devservices.commands.toggle.subprocess.run")
def test_restart_dependent_services_multiple_dependent_services_multiple_modes(
    mock_subprocess_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    restart_dependent_services(
        "example-service",
        {
            "dependent-service": ["default", "other-mode"],
            "other-dependent-service": ["default", "other-mode"],
        },
    )

    mock_subprocess_run.assert_has_calls(
        [
            mock.call(
                ["devservices", "up", "dependent-service", "--mode", "default"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
            mock.call(
                ["devservices", "up", "dependent-service", "--mode", "other-mode"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
            mock.call(
                ["devservices", "up", "other-dependent-service", "--mode", "default"],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
            mock.call(
                [
                    "devservices",
                    "up",
                    "other-dependent-service",
                    "--mode",
                    "other-mode",
                ],
                check=True,
                text=True,
                stdout=mock.ANY,
            ),
        ]
    )

    captured = capsys.readouterr()

    assert (
        f"Restarting dependent services to ensure example-service is running in a {ServiceRuntime.CONTAINERIZED.value} runtime"
        in captured.out.strip()
    )
    assert "Restarting dependent-service in mode default" in captured.out.strip()
    assert "Restarting dependent-service in mode other-mode" in captured.out.strip()
    assert "Restarting other-dependent-service in mode default" in captured.out.strip()
    assert (
        "Restarting other-dependent-service in mode other-mode" in captured.out.strip()
    )


@mock.patch("devservices.commands.toggle.subprocess.run")
def test_restart_dependent_services_failure(
    mock_subprocess_run: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["devservices", "up", "dependent-service", "--mode", "default"],
    )

    with pytest.raises(SystemExit):
        restart_dependent_services(
            "example-service", {"dependent-service": ["default"]}
        )

    captured = capsys.readouterr()

    assert (
        "Failed to restart services, please try starting them manually"
        in captured.out.strip()
    )


@mock.patch("devservices.commands.toggle.install_and_verify_dependencies")
def test_bring_down_containerized_service_install_and_verify_dependencies_failure(
    mock_install_and_verify_dependencies: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    example_service_path = tmp_path / "example-service"
    example_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "clickhouse": {
                    "description": "Clickhouse",
                },
            },
            "modes": {"default": ["clickhouse"]},
        },
    }
    create_config_file(example_service_path, example_service_config)
    mock_install_and_verify_dependencies.side_effect = DependencyError(
        branch="main",
        repo_link=str(example_service_path),
        repo_name="example-service",
        stderr="Failed to install and verify dependencies",
    )

    with pytest.raises(SystemExit):
        bring_down_containerized_service(
            Service(
                name="example-service",
                repo_path=str(example_service_path),
                config=ServiceConfig(
                    version=0.1,
                    service_name="example-service",
                    dependencies={
                        "clickhouse": Dependency(
                            description="Clickhouse",
                            remote=None,
                        ),
                    },
                    modes={"default": ["clickhouse"]},
                ),
            ),
            ["default"],
        )

    captured = capsys.readouterr()

    assert "DependencyError: example-service" in captured.out.strip()


@mock.patch("devservices.commands.toggle.install_and_verify_dependencies")
@mock.patch("devservices.commands.toggle.get_non_shared_remote_dependencies")
@mock.patch("devservices.commands.toggle.bring_down_service")
def test_bring_down_containerized_service_no_remote_dependencies(
    mock_bring_down_service: mock.Mock,
    mock_get_non_shared_remote_dependencies: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    example_service_path = tmp_path / "example-service"
    example_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "clickhouse": {
                    "description": "Clickhouse",
                },
            },
            "modes": {"default": ["clickhouse"]},
        },
    }
    create_config_file(example_service_path, example_service_config)

    mock_install_and_verify_dependencies.return_value = set()
    mock_get_non_shared_remote_dependencies.return_value = set()

    bring_down_containerized_service(
        Service(
            name="example-service",
            repo_path=str(example_service_path),
            config=ServiceConfig(
                version=0.1,
                service_name="example-service",
                dependencies={
                    "clickhouse": Dependency(
                        description="Clickhouse",
                        remote=None,
                    ),
                },
                modes={"default": ["clickhouse"]},
            ),
        ),
        ["default"],
    )

    mock_bring_down_service.assert_called_once_with(
        Service(
            name="example-service",
            repo_path=str(example_service_path),
            config=ServiceConfig(
                version=0.1,
                service_name="example-service",
                dependencies={
                    "clickhouse": Dependency(description="Clickhouse", remote=None),
                },
                modes={"default": ["clickhouse"]},
            ),
        ),
        set(),
        ["clickhouse"],
        mock.ANY,
    )


@mock.patch("devservices.commands.toggle.bring_down_service")
@mock.patch("devservices.commands.toggle.install_and_verify_dependencies")
@mock.patch("devservices.commands.toggle.get_non_shared_remote_dependencies")
def test_bring_down_containerized_service_with_remote_dependency(
    mock_get_non_shared_remote_dependencies: mock.Mock,
    mock_install_and_verify_dependencies: mock.Mock,
    mock_bring_down_service: mock.Mock,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    redis_repo_path = create_mock_git_repo("blank_repo", tmp_path / "redis")
    redis_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "redis",
            "dependencies": {
                "redis": {
                    "description": "Redis",
                },
            },
            "modes": {"default": ["redis"]},
        },
    }
    create_config_file(redis_repo_path, redis_config)
    run_git_command(["add", "."], cwd=redis_repo_path)
    run_git_command(["commit", "-m", "Add devservices config"], cwd=redis_repo_path)

    example_service_path = tmp_path / "example-service"
    example_service_config = {
        "x-sentry-service-config": {
            "version": 0.1,
            "service_name": "example-service",
            "dependencies": {
                "clickhouse": {
                    "description": "Clickhouse",
                },
                "redis": {
                    "description": "Redis",
                    "remote": {
                        "repo_name": "redis",
                        "repo_link": f"file://{redis_repo_path}",
                    },
                },
            },
            "modes": {"default": ["clickhouse", "redis"]},
        },
    }
    create_config_file(example_service_path, example_service_config)
    run_git_command(["add", "."], cwd=example_service_path)
    run_git_command(
        ["commit", "-m", "Add devservices config"], cwd=example_service_path
    )

    mock_install_and_verify_dependencies.return_value = {
        InstalledRemoteDependency(
            service_name="redis",
            repo_path=str(redis_repo_path),
            mode="default",
        ),
    }

    mock_get_non_shared_remote_dependencies.return_value = {
        InstalledRemoteDependency(
            service_name="redis",
            repo_path=str(redis_repo_path),
            mode="default",
        ),
    }

    bring_down_containerized_service(
        Service(
            name="example-service",
            repo_path=str(example_service_path),
            config=ServiceConfig(
                version=0.1,
                service_name="example-service",
                dependencies={
                    "clickhouse": Dependency(description="Clickhouse", remote=None),
                    "redis": Dependency(
                        description="Redis",
                        remote=RemoteConfig(
                            repo_name="redis",
                            repo_link=f"file://{redis_repo_path}",
                            branch="main",
                            mode="default",
                        ),
                    ),
                },
                modes={"default": ["clickhouse", "redis"]},
            ),
        ),
        ["default"],
    )

    mock_bring_down_service.assert_has_calls(
        [
            mock.call(
                Service(
                    name="example-service",
                    repo_path=str(example_service_path),
                    config=ServiceConfig(
                        version=0.1,
                        service_name="example-service",
                        dependencies={
                            "clickhouse": Dependency(
                                description="Clickhouse", remote=None
                            ),
                            "redis": Dependency(
                                description="Redis",
                                remote=RemoteConfig(
                                    repo_name="redis",
                                    repo_link=f"file://{redis_repo_path}",
                                    branch="main",
                                    mode="default",
                                ),
                            ),
                        },
                        modes={"default": ["clickhouse", "redis"]},
                    ),
                ),
                {
                    InstalledRemoteDependency(
                        service_name="redis",
                        repo_path=str(redis_repo_path),
                        mode="default",
                    ),
                },
                ["clickhouse", "redis"],
                mock.ANY,
            ),
        ]
    )
