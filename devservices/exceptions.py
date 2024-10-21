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


class DependencyError(Exception):
    """Base class for dependency-related errors."""

    def __init__(self, repo_name: str, repo_link: str, branch: str):
        self.repo_name = repo_name
        self.repo_link = repo_link
        self.branch = branch


class InvalidDependencyConfigError(DependencyError):
    """Raised when a dependency's config is invalid."""

    pass


class DependencyNotInstalledError(DependencyError):
    """Raised when a dependency is not installed correctly."""

    pass


class GitConfigError(Exception):
    """Base class for git config related errors."""

    pass


class FailedToSetGitConfigError(GitConfigError):
    """Raised when a git config cannot be set."""

    pass
