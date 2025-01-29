from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.exceptions import GitError
from devservices.utils.git import get_git_version


@mock.patch(
    "devservices.utils.git.subprocess.check_output", return_value="git version 2.42.0"
)
def test_get_git_version_success(mock_get_git_version: mock.Mock) -> None:
    assert get_git_version() == "git version 2.42.0"
    mock_get_git_version.assert_called_once_with(
        ["git", "version"], text=True, stderr=subprocess.PIPE
    )


@mock.patch(
    "devservices.utils.git.subprocess.check_output",
    side_effect=subprocess.CalledProcessError(
        returncode=1, cmd="git version", stderr="error"
    ),
)
def test_get_git_version_error(mock_get_git_version: mock.Mock) -> None:
    with pytest.raises(GitError):
        get_git_version()
    mock_get_git_version.assert_called_once_with(
        ["git", "version"], text=True, stderr=subprocess.PIPE
    )
