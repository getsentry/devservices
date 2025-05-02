from __future__ import annotations


class ServiceNotFoundError(Exception):
    """Raised when a service is not found."""

    pass


class ConfigError(Exception):
    """Base class for configuration-related errors."""

    pass


class ConfigNotFoundError(ConfigError):
    """Raised when a configuration file is not found."""

    pass


class ConfigValidationError(ConfigError):
    """Raised when a configuration file is invalid."""

    pass


class ConfigParseError(ConfigError):
    """Raised when a configuration file cannot be parsed."""

    pass


class BinaryInstallError(Exception):
    """Raised when a binary cannot be installed."""

    pass


class DevservicesUpdateError(BinaryInstallError):
    """Raised when the devservices update fails."""

    pass


class DockerDaemonNotRunningError(Exception):
    """Raised when the Docker daemon is not running."""

    def __str__(self) -> str:
        # TODO: Provide explicit instructions on what to do
        return "Unable to connect to the docker daemon. Is the docker daemon running?"


class DockerComposeInstallationError(BinaryInstallError):
    """Raised when the Docker Compose installation fails."""

    pass


class DockerError(Exception):
    """Base class for Docker related errors."""

    def __init__(self, command: str, returncode: int, stdout: str, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class DockerComposeError(DockerError):
    """Base class for Docker Compose related errors."""

    def __str__(self) -> str:
        return f"DockerComposeError: {self.command} returned {self.returncode} error: {self.stderr}"


class ModeDoesNotExistError(Exception):
    """Raised when a mode does not exist."""

    def __init__(self, service_name: str, mode: str, available_modes: list[str]):
        self.service_name = service_name
        self.mode = mode
        self.available_modes = available_modes

    def __str__(self) -> str:
        # All valid services should have at least one mode, so we don't check for an empty list
        return f"ModeDoesNotExistError: Mode '{self.mode}' does not exist for service '{self.service_name}'.\nAvailable modes: {', '.join(self.available_modes)}"


class DependencyError(Exception):
    """Base class for dependency-related errors."""

    def __init__(
        self, repo_name: str, repo_link: str, branch: str, stderr: str | None = None
    ):
        self.repo_name = repo_name
        self.repo_link = repo_link
        self.branch = branch
        self.stderr = stderr

    def __str__(self) -> str:
        return f"DependencyError: {self.repo_name} ({self.repo_link}) on {self.branch}"


class UnableToCloneDependencyError(DependencyError):
    """Raised when a dependency is unable to be cloned."""

    def __str__(self) -> str:
        return f"Unable to clone dependency: {self.repo_name} ({self.repo_link}) on {self.branch}"


class InvalidDependencyConfigError(DependencyError):
    """Raised when a dependency's config is invalid."""

    def __str__(self) -> str:
        return f"Invalid config for dependency: {self.repo_name} ({self.repo_link}) on {self.branch}"


class DependencyNotInstalledError(DependencyError):
    """Raised when a dependency is not installed correctly."""

    def __str__(self) -> str:
        return f"Dependency not installed correctly: {self.repo_name} ({self.repo_link}) on {self.branch}"


class CannotToggleNonRemoteServiceError(Exception):
    """Raised when a non-remote service is attempted to be toggled."""

    def __init__(self, service_name: str):
        self.service_name = service_name

    def __str__(self) -> str:
        return f"Cannot toggle {self.service_name} because it is not a remote service. This is likely because of a naming conflict."


class GitError(Exception):
    """Base class for git related errors."""

    def __init__(self, command: str, returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class GitConfigError(Exception):
    """Base class for git config related errors."""

    pass


class FailedToSetGitConfigError(GitConfigError):
    """Raised when a git config cannot be set."""

    pass


class ContainerHealthcheckFailedError(Exception):
    """Raised when a container is not healthy."""

    def __init__(self, container_name: str, timeout: int):
        self.container_name = container_name
        self.timeout = timeout

    def __str__(self) -> str:
        return f"Container {self.container_name} did not become healthy within {self.timeout} seconds."


class SupervisorError(Exception):
    """Base exception for supervisor-related errors."""

    pass


class SupervisorConfigError(SupervisorError):
    """Raised when there's an error with the supervisor configuration."""

    pass


class SupervisorConnectionError(SupervisorError):
    """Raised when unable to connect to the supervisor XML-RPC server."""

    pass


class SupervisorProcessError(SupervisorError):
    """Raised when there's an error with a supervisor process."""

    pass
