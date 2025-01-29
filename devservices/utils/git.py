from __future__ import annotations

import subprocess

from devservices.exceptions import GitError


def get_git_version() -> str:
    """Get the git version"""
    try:
        return subprocess.check_output(
            ["git", "version"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as e:
        raise GitError(
            command="git --version",
            returncode=e.returncode,
            stderr=e.stderr,
        ) from e
