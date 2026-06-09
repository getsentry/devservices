from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from devservices.utils import github


def test_parse_repo_path_valid() -> None:
    assert (
        github.parse_repo_path("https://github.com/getsentry/test-repo")
        == "getsentry/test-repo"
    )
    assert (
        github.parse_repo_path("https://github.com/getsentry/test-repo.git")
        == "getsentry/test-repo"
    )
    assert (
        github.parse_repo_path("https://github.com/getsentry/test-repo/")
        == "getsentry/test-repo"
    )
    assert github.parse_repo_path("http://github.com/org/repo") == "org/repo"


def test_parse_repo_path_non_github() -> None:
    with pytest.raises(ValueError):
        github.parse_repo_path("file:///path/to/repo")
    with pytest.raises(ValueError):
        github.parse_repo_path("invalid-link")
    with pytest.raises(ValueError):
        github.parse_repo_path("https://gitlab.com/org/repo")


def test_zipball_url() -> None:
    assert (
        github.zipball_url("getsentry/test-repo", "main")
        == "https://api.github.com/repos/getsentry/test-repo/zipball/main"
    )


def test_api_headers_with_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    headers = github.api_headers()
    assert headers["Accept"] == github.GITHUB_API_ACCEPT
    assert headers["Authorization"] == "Bearer secret-token"


def test_api_headers_falls_back_to_gh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-env-token")
    headers = github.api_headers()
    assert headers["Authorization"] == "Bearer gh-env-token"


def test_api_headers_with_gh_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with (
        mock.patch("devservices.utils.github.shutil.which", return_value="/usr/bin/gh"),
        mock.patch(
            "devservices.utils.github.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="gh-token\n", stderr=""
            ),
        ),
    ):
        headers = github.api_headers()
    assert headers["Authorization"] == "Bearer gh-token"


def test_api_headers_unauthenticated_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("devservices.utils.github._auth_warned", False)
    with (
        mock.patch("devservices.utils.github.shutil.which", return_value=None),
        mock.patch("devservices.utils.github.Console.warning") as warning_mock,
    ):
        headers = github.api_headers()
    assert "Authorization" not in headers
    warning_mock.assert_called_once()


def test_api_headers_gh_cli_not_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("devservices.utils.github._auth_warned", False)
    with (
        mock.patch("devservices.utils.github.shutil.which", return_value="/usr/bin/gh"),
        mock.patch(
            "devservices.utils.github.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not logged in"
            ),
        ),
        mock.patch("devservices.utils.github.Console.warning") as warning_mock,
    ):
        headers = github.api_headers()
    assert "Authorization" not in headers
    warning_mock.assert_called_once()


def test_warn_unauthenticated_only_warns_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("devservices.utils.github._auth_warned", False)
    with mock.patch("devservices.utils.github.Console.warning") as warning_mock:
        github._warn_unauthenticated()
        github._warn_unauthenticated()
    warning_mock.assert_called_once()
