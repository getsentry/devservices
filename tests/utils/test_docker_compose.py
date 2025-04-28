from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from devservices.configs.service_config import load_service_config_from_file
from devservices.constants import CONFIG_FILE_NAME
from devservices.constants import DEVSERVICES_DIR_NAME
from devservices.exceptions import BinaryInstallError
from devservices.exceptions import DockerComposeError
from devservices.exceptions import DockerComposeInstallationError
from devservices.exceptions import DockerDaemonNotRunningError
from devservices.utils.dependencies import InstalledRemoteDependency
from devservices.utils.docker import ContainerNames
from devservices.utils.docker_compose import check_docker_compose_version
from devservices.utils.docker_compose import DockerComposeCommand
from devservices.utils.docker_compose import get_container_names_for_project
from devservices.utils.docker_compose import get_docker_compose_commands_to_run
from devservices.utils.docker_compose import get_docker_compose_version
from devservices.utils.docker_compose import get_non_remote_services
from devservices.utils.docker_compose import install_docker_compose
from devservices.utils.services import Service
from testing.utils import create_mock_git_repo


@mock.patch("subprocess.run")
def test_check_docker_compose_version_success(mock_run: mock.Mock) -> None:
    mock_run.return_value.stdout = "2.29.7\n"
    check_docker_compose_version()  # Should not raise any exception


@mock.patch("subprocess.run")
def test_get_docker_compose_version(mock_run: mock.Mock) -> None:
    mock_run.return_value.stdout = "2.29.7\n"
    assert get_docker_compose_version() == "2.29.7"


@mock.patch(
    "subprocess.run",
    side_effect=subprocess.CalledProcessError(
        returncode=1,
        cmd="docker compose version --short",
        stderr="Docker Compose failed",
    ),
)
def test_get_docker_compose_version_error(mock_run: mock.Mock) -> None:
    with pytest.raises(DockerComposeError) as e:
        get_docker_compose_version()
    assert e.value.stderr == "Docker Compose failed"


@mock.patch("subprocess.run")
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_version_unsupported(
    mock_install_docker_compose: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "2.20.0-desktop.1\n"
    check_docker_compose_version()
    assert mock_install_docker_compose.is_called()


@mock.patch("subprocess.run")
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_invalid_version(
    mock_install_docker_compose: mock.Mock, mock_run: mock.Mock
) -> None:
    mock_run.return_value.stdout = "Unable to find version\n"
    check_docker_compose_version()
    mock_install_docker_compose.assert_called_once()


@mock.patch(
    "subprocess.run",
    side_effect=[subprocess.CalledProcessError(returncode=1, cmd="docker info")],
)
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_docker_daemon_not_running(
    mock_install_docker_compose: mock.Mock, _mock_run: mock.Mock
) -> None:
    with pytest.raises(
        DockerDaemonNotRunningError,
        match="Unable to connect to the docker daemon. Is the docker daemon running?",
    ):
        check_docker_compose_version()
    mock_install_docker_compose.assert_not_called()


@mock.patch(
    "subprocess.run",
    side_effect=[
        0,  # First call is to check if docker daemon is running
    ],
)
@mock.patch(
    "devservices.utils.docker_compose.get_docker_compose_version",
    side_effect=DockerComposeError(
        command="docker compose version --short",
        returncode=1,
        stdout="",
        stderr="",
    ),
)
@mock.patch(
    "devservices.utils.docker_compose.install_docker_compose", side_effect=lambda: None
)
def test_check_docker_compose_command_failure(
    mock_install_docker_compose: mock.Mock,
    mock_get_docker_compose_version: mock.Mock,
    _mock_run: mock.Mock,
) -> None:
    check_docker_compose_version()
    mock_get_docker_compose_version.assert_called_once()
    mock_install_docker_compose.assert_called_once()


@mock.patch("platform.system", return_value="UnsupportedSystem")
@mock.patch("platform.machine", return_value="arm64")
def test_install_docker_compose_unsupported_os(
    _mock_system: mock.Mock, _mock_machine: mock.Mock
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Unsupported operating system: UnsupportedSystem",
    ):
        install_docker_compose()


@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="unsupported_architecture")
def test_install_docker_compose_unsupported_architecture(
    _mock_machine: mock.Mock, _mock_system: mock.Mock
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Unsupported architecture: unsupported_architecture",
    ):
        install_docker_compose()


@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch(
    "devservices.utils.docker_compose.install_binary",
    side_effect=BinaryInstallError("Installation error"),
)
def test_install_docker_compose_binary_install_error(
    _mock_install_binary: mock.Mock,
    _mock_machine: mock.Mock,
    _mock_system: mock.Mock,
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Failed to install Docker Compose: Installation error",
    ):
        install_docker_compose()


@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.get_docker_compose_version",
    side_effect=DockerComposeError(
        command="docker compose version --short",
        returncode=1,
        stdout="",
        stderr="Docker Compose failed",
    ),
)
def test_install_docker_compose_compose_verification_error(
    _mock_get_docker_compose_version: mock.Mock,
    _mock_shutil_move: mock.Mock,
    _mock_chmod: mock.Mock,
    _mock_urlretrieve: mock.Mock,
    _mock_machine: mock.Mock,
    _mock_system: mock.Mock,
) -> None:
    with pytest.raises(
        DockerComposeInstallationError,
        match="Failed to verify Docker Compose installation: Docker Compose failed",
    ):
        install_docker_compose()


@mock.patch("devservices.utils.install_binary.tempfile.TemporaryDirectory")
@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.get_docker_compose_version",
    return_value="2.29.7\n",
)
def test_install_docker_compose_macos_arm64(
    mock_get_docker_compose_version: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    _mock_machine: mock.Mock,
    _mock_system: mock.Mock,
    mock_tempdir: mock.Mock,
) -> None:
    mock_tempdir.return_value.__enter__.return_value = "tempdir"
    install_docker_compose()
    mock_urlretrieve.assert_called_once_with(
        "https://storage.googleapis.com/sentry-dev-infra-assets/docker-compose/v2.29.7/docker-compose-darwin-aarch64",
        "tempdir/docker-compose",
    )
    mock_chmod.assert_called_once_with("tempdir/docker-compose", 0o755)
    mock_shutil_move.assert_called_once_with(
        "tempdir/docker-compose",
        os.path.expanduser("~/.docker/cli-plugins/docker-compose"),
    )
    mock_get_docker_compose_version.assert_called_once()


@mock.patch("devservices.utils.install_binary.tempfile.TemporaryDirectory")
@mock.patch("platform.system", return_value="Linux")
@mock.patch("platform.machine", return_value="x86_64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.get_docker_compose_version",
    return_value="2.29.7\n",
)
def test_install_docker_compose_linux_x86(
    mock_get_docker_compose_version: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    _mock_machine: mock.Mock,
    _mock_system: mock.Mock,
    mock_tempdir: mock.Mock,
) -> None:
    mock_tempdir.return_value.__enter__.return_value = "tempdir"
    install_docker_compose()
    mock_urlretrieve.assert_called_once_with(
        "https://storage.googleapis.com/sentry-dev-infra-assets/docker-compose/v2.29.7/docker-compose-linux-x86_64",
        "tempdir/docker-compose",
    )
    mock_chmod.assert_called_once_with("tempdir/docker-compose", 0o755)
    mock_shutil_move.assert_called_once_with(
        "tempdir/docker-compose",
        os.path.expanduser("~/.docker/cli-plugins/docker-compose"),
    )
    mock_get_docker_compose_version.assert_called_once()


@mock.patch("devservices.utils.install_binary.tempfile.TemporaryDirectory")
@mock.patch("platform.system", return_value="Darwin")
@mock.patch("platform.machine", return_value="arm64")
@mock.patch("devservices.utils.install_binary.urlretrieve")
@mock.patch("devservices.utils.install_binary.os.chmod")
@mock.patch("devservices.utils.install_binary.shutil.move")
@mock.patch(
    "devservices.utils.docker_compose.get_docker_compose_version",
    return_value="2.29.7\n",
)
def test_install_docker_compose_custom_docker_config_dir(
    mock_get_docker_compose_version: mock.Mock,
    mock_shutil_move: mock.Mock,
    mock_chmod: mock.Mock,
    mock_urlretrieve: mock.Mock,
    _mock_machine: mock.Mock,
    _mock_system: mock.Mock,
    mock_tempdir: mock.Mock,
) -> None:
    mock_tempdir.return_value.__enter__.return_value = "tempdir"
    with mock.patch(
        "devservices.utils.docker_compose.DOCKER_USER_PLUGIN_DIR",
        "tempdir/docker/config/cli-plugins",
    ):
        install_docker_compose()
    mock_urlretrieve.assert_called_once_with(
        "https://storage.googleapis.com/sentry-dev-infra-assets/docker-compose/v2.29.7/docker-compose-darwin-aarch64",
        "tempdir/docker-compose",
    )
    mock_chmod.assert_called_once_with("tempdir/docker-compose", 0o755)
    mock_shutil_move.assert_called_once_with(
        "tempdir/docker-compose",
        "tempdir/docker/config/cli-plugins/docker-compose",
    )
    mock_get_docker_compose_version.assert_called_once()


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="service-1\nservice-2\n",
    ),
)
def test_get_non_remote_services_success(_mock_run: mock.Mock) -> None:
    services = get_non_remote_services("config_path", {})
    assert services == {"service-1", "service-2"}


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    side_effect=subprocess.CalledProcessError(
        returncode=1, cmd="docker compose config --services", stderr="command failed"
    ),
)
def test_get_non_remote_services_error(_mock_run: mock.Mock) -> None:
    with pytest.raises(DockerComposeError) as e:
        get_non_remote_services("config_path", {})
        assert str(e.value) == "command failed"


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="child-service\n",
    ),
)
def test_get_all_commands_to_run_simple_local(
    _mock_run: mock.Mock, tmp_path: Path
) -> None:
    child_service_repo_path = tmp_path / "child-service-repo"
    create_mock_git_repo("child-service-repo", child_service_repo_path)
    child_service_repo_path_str = str(child_service_repo_path)
    service_config = load_service_config_from_file(child_service_repo_path_str)
    remote_dependencies: list[InstalledRemoteDependency] = []
    current_env = os.environ.copy()
    command = "up"
    options = ["-d"]
    service_config_file_path = os.path.join(
        child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    mode_dependencies = service_config.modes["default"]
    service = Service(
        name="child-service",
        repo_path=child_service_repo_path_str,
        config=service_config,
    )
    commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=list(remote_dependencies),
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )
    assert commands == [
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "child-service",
                "-f",
                service_config_file_path,
                "up",
                "child-service",
                "-d",
            ],
            project_name="child-service",
            config_path=service_config_file_path,
            services=["child-service"],
        ),
    ]


@mock.patch(
    "devservices.utils.docker_compose.subprocess.run",
    return_value=subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--services"],
        returncode=0,
        stdout="child-service\n",
    ),
)
def test_get_all_commands_to_run_no_services_to_use(
    _mock_run: mock.Mock, tmp_path: Path
) -> None:
    child_service_repo_path = tmp_path / "child-service-repo"
    create_mock_git_repo("child-service-repo", child_service_repo_path)
    child_service_repo_path_str = str(child_service_repo_path)
    service_config = load_service_config_from_file(child_service_repo_path_str)
    remote_dependencies: list[InstalledRemoteDependency] = []
    current_env = os.environ.copy()
    command = "up"
    options = ["-d"]
    service_config_file_path = os.path.join(
        child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    mode_dependencies = ["random-service"]
    service = Service(
        name="child-service",
        repo_path=child_service_repo_path_str,
        config=service_config,
    )
    commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=remote_dependencies,
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )
    assert commands == []


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_get_all_commands_to_run_simple_remote(
    mock_run: mock.Mock, tmp_path: Path
) -> None:
    child_service_repo_path = tmp_path / "child-service-repo"
    parent_service_repo_path = tmp_path / "parent-service-repo"
    create_mock_git_repo("child-service-repo", child_service_repo_path)
    create_mock_git_repo("parent-service-repo", parent_service_repo_path)
    child_service_repo_path_str = str(child_service_repo_path)
    parent_service_repo_path_str = str(parent_service_repo_path)
    service_config = load_service_config_from_file(parent_service_repo_path_str)
    service = Service(
        name="parent-service",
        repo_path=parent_service_repo_path_str,
        config=service_config,
    )
    remote_dependencies = [
        InstalledRemoteDependency(
            service_name="child-service",
            repo_path=child_service_repo_path_str,
            mode="default",
        )
    ]
    current_env = os.environ.copy()
    command = "up"
    options = ["-d"]
    service_config_file_path = os.path.join(
        parent_service_repo_path, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    mode_dependencies = service_config.modes["default"]
    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="child-service\n",
        ),
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="parent-service\n",
        ),
    ]
    commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=remote_dependencies,
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )
    assert commands == [
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "child-service",
                "-f",
                os.path.join(
                    child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
                ),
                "up",
                "child-service",
                "-d",
            ],
            project_name="child-service",
            config_path=os.path.join(
                child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["child-service"],
        ),
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "parent-service",
                "-f",
                service_config_file_path,
                "up",
                "parent-service",
                "-d",
            ],
            project_name="parent-service",
            config_path=os.path.join(
                parent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["parent-service"],
        ),
    ]


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_get_all_commands_to_run_complex_remote(
    mock_run: mock.Mock, tmp_path: Path
) -> None:
    child_service_repo_path = tmp_path / "child-service-repo"
    parent_service_repo_path = tmp_path / "parent-service-repo"
    grandparent_service_repo_path = tmp_path / "grandparent-service-repo"
    create_mock_git_repo("child-service-repo", tmp_path / "child-service-repo")
    create_mock_git_repo("parent-service-repo", tmp_path / "parent-service-repo")
    create_mock_git_repo(
        "grandparent-service-repo", tmp_path / "grandparent-service-repo"
    )
    child_service_repo_path_str = str(child_service_repo_path)
    parent_service_repo_path_str = str(parent_service_repo_path)
    grandparent_service_repo_path_str = str(grandparent_service_repo_path)
    service_config = load_service_config_from_file(grandparent_service_repo_path_str)
    service = Service(
        name="grandparent-service",
        repo_path=grandparent_service_repo_path_str,
        config=service_config,
    )
    remote_dependencies = [
        InstalledRemoteDependency(
            service_name="child-service",
            repo_path=child_service_repo_path_str,
            mode="default",
        ),
        InstalledRemoteDependency(
            service_name="parent-service",
            repo_path=parent_service_repo_path_str,
            mode="default",
        ),
    ]
    current_env = os.environ.copy()
    command = "up"
    options = ["-d"]
    service_config_file_path = os.path.join(
        grandparent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    mode_dependencies = service_config.modes["default"]
    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="child-service\n",
        ),
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="parent-service\n",
        ),
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="grandparent-service\n",
        ),
    ]
    commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=list(remote_dependencies),
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )
    assert commands == [
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "child-service",
                "-f",
                os.path.join(
                    child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
                ),
                "up",
                "child-service",
                "-d",
            ],
            project_name="child-service",
            config_path=os.path.join(
                child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["child-service"],
        ),
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "parent-service",
                "-f",
                os.path.join(
                    parent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
                ),
                "up",
                "parent-service",
                "-d",
            ],
            project_name="parent-service",
            config_path=os.path.join(
                parent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["parent-service"],
        ),
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "grandparent-service",
                "-f",
                service_config_file_path,
                "up",
                "grandparent-service",
                "-d",
            ],
            project_name="grandparent-service",
            config_path=os.path.join(
                grandparent_service_repo_path_str,
                DEVSERVICES_DIR_NAME,
                CONFIG_FILE_NAME,
            ),
            services=["grandparent-service"],
        ),
    ]


@mock.patch("devservices.utils.docker_compose.subprocess.run")
def test_get_all_commands_to_run_complex_shared_dependency(
    mock_run: mock.Mock, tmp_path: Path
) -> None:
    child_service_repo_path = tmp_path / "child-service-repo"
    parent_service_repo_path = tmp_path / "parent-service-repo"
    grandparent_service_repo_path = tmp_path / "grandparent-service-repo"
    create_mock_git_repo("child-service-repo", tmp_path / "child-service-repo")
    create_mock_git_repo("parent-service-repo", tmp_path / "parent-service-repo")
    create_mock_git_repo(
        "grandparent-service-repo", tmp_path / "grandparent-service-repo"
    )
    child_service_repo_path_str = str(child_service_repo_path)
    parent_service_repo_path_str = str(parent_service_repo_path)
    grandparent_service_repo_path_str = str(grandparent_service_repo_path)
    service_config = load_service_config_from_file(grandparent_service_repo_path_str)
    service = Service(
        name="grandparent-service",
        repo_path=grandparent_service_repo_path_str,
        config=service_config,
    )
    remote_dependencies = [
        InstalledRemoteDependency(
            service_name="child-service",
            repo_path=child_service_repo_path_str,
            mode="default",
        ),
        InstalledRemoteDependency(
            service_name="shared-parent-service",
            repo_path=parent_service_repo_path_str,
            mode="default",
        ),
    ]
    current_env = os.environ.copy()
    command = "up"
    options = ["-d"]
    service_config_file_path = os.path.join(
        grandparent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
    )
    mode_dependencies = service_config.modes["default"]
    mock_run.side_effect = [
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="child-service\n",
        ),
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="parent-service\n",
        ),
        subprocess.CompletedProcess(
            args=["docker", "compose", "config", "--services"],
            returncode=0,
            stdout="grandparent-service\n",
        ),
    ]
    commands = get_docker_compose_commands_to_run(
        service=service,
        remote_dependencies=remote_dependencies,
        current_env=current_env,
        command=command,
        options=options,
        service_config_file_path=service_config_file_path,
        mode_dependencies=mode_dependencies,
    )
    assert commands == [
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "child-service",
                "-f",
                os.path.join(
                    child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
                ),
                "up",
                "child-service",
                "-d",
            ],
            project_name="child-service",
            config_path=os.path.join(
                child_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["child-service"],
        ),
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "parent-service",
                "-f",
                os.path.join(
                    parent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
                ),
                "up",
                "parent-service",
                "-d",
            ],
            project_name="parent-service",
            config_path=os.path.join(
                parent_service_repo_path_str, DEVSERVICES_DIR_NAME, CONFIG_FILE_NAME
            ),
            services=["parent-service"],
        ),
        DockerComposeCommand(
            full_command=[
                "docker",
                "compose",
                "-p",
                "grandparent-service",
                "-f",
                service_config_file_path,
                "up",
                "grandparent-service",
                "-d",
            ],
            project_name="grandparent-service",
            config_path=os.path.join(
                grandparent_service_repo_path_str,
                DEVSERVICES_DIR_NAME,
                CONFIG_FILE_NAME,
            ),
            services=["grandparent-service"],
        ),
    ]


@mock.patch("devservices.utils.docker_compose.subprocess.check_output")
def test_get_container_names_for_project_success(_mock_check_output: mock.Mock) -> None:
    _mock_check_output.return_value = '{"name": "devservices-container1", "short_name": "container1"}\n{"name": "devservices-container2", "short_name": "container2"}'
    assert get_container_names_for_project(
        "project", "config_path", ["container1", "container2"]
    ) == [
        ContainerNames(name="devservices-container1", short_name="container1"),
        ContainerNames(name="devservices-container2", short_name="container2"),
    ]


@mock.patch("devservices.utils.docker_compose.subprocess.check_output")
def test_get_container_names_for_project_error(_mock_check_output: mock.Mock) -> None:
    _mock_check_output.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd="docker compose ps --format", stderr="command failed"
    )
    with pytest.raises(DockerComposeError) as e:
        get_container_names_for_project(
            "project", "config_path", ["container1", "container2"]
        )
    assert e.value.stderr == "command failed"
