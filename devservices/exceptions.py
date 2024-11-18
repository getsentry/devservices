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


class DockerComposeError(Exception):
    """Base class for Docker Compose related errors."""

    def __init__(self, command: str, returncode: int, stdout: str, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ModeDoesNotExistError(Exception):
    """Raised when a mode does not exist."""

    def __init__(self, service_name: str, mode: str):
        self.service_name = service_name
        self.mode = mode

    def __str__(self) -> str:
        return f"ModeDoesNotExistError: Mode '{self.mode}' does not exist for service '{self.service_name}'"


class DependencyError(Exception):
    """Base class for dependency-related errors."""

    def __init__(self, repo_name: str, repo_link: str, branch: str):
        self.repo_name = repo_name
        self.repo_link = repo_link
        self.branch = branch

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


class GitConfigError(Exception):
    """Base class for git config related errors."""

    pass


class FailedToSetGitConfigError(GitConfigError):
    """Raised when a git config cannot be set."""

    pass
