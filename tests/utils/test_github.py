from __future__ import annotations

import io
import os
import subprocess
import urllib.request
import zipfile
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


def test_parse_repo_path_ssh() -> None:
    assert (
        github.parse_repo_path("git@github.com:getsentry/test-repo")
        == "getsentry/test-repo"
    )
    assert (
        github.parse_repo_path("git@github.com:getsentry/test-repo.git")
        == "getsentry/test-repo"
    )


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


def test_build_api_request_with_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    req = github.build_api_request("https://api.github.com/x")
    assert req.get_header("Accept") == github.GITHUB_API_ACCEPT
    # Token must be an unredirected header so it isn't forwarded on redirect.
    assert req.unredirected_hdrs.get("Authorization") == "Bearer secret-token"
    assert "Authorization" not in req.headers


def test_build_api_request_falls_back_to_gh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-env-token")
    req = github.build_api_request("https://api.github.com/x")
    assert req.unredirected_hdrs.get("Authorization") == "Bearer gh-env-token"


def test_build_api_request_with_gh_cli(monkeypatch: pytest.MonkeyPatch) -> None:
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
        req = github.build_api_request("https://api.github.com/x")
    assert req.unredirected_hdrs.get("Authorization") == "Bearer gh-token"


def test_build_api_request_unauthenticated_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("devservices.utils.github._auth_warned", False)
    with (
        mock.patch("devservices.utils.github.shutil.which", return_value=None),
        mock.patch("devservices.utils.github.Console.warning") as warning_mock,
    ):
        req = github.build_api_request("https://api.github.com/x")
    assert req.get_header("Authorization") is None
    warning_mock.assert_called_once()


def test_build_api_request_gh_cli_not_authenticated(
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
        req = github.build_api_request("https://api.github.com/x")
    assert req.get_header("Authorization") is None
    warning_mock.assert_called_once()


def test_warn_unauthenticated_only_warns_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("devservices.utils.github._auth_warned", False)
    with mock.patch("devservices.utils.github.Console.warning") as warning_mock:
        github._warn_unauthenticated()
        github._warn_unauthenticated()
    warning_mock.assert_called_once()


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CI"), reason="hits real GitHub; runs in CI only"
)
def test_build_api_request_downloads_real_zip() -> None:
    # End-to-end check that a real zipball download works: the request follows
    # the api.github.com -> codeload.github.com 302 redirect, and the (possibly
    # authenticated) Authorization header isn't forwarded in a way that breaks
    # the download. chartcuterie is a small public repo (~280KB zip).
    url = github.zipball_url("getsentry/chartcuterie", "master")
    req = github.build_api_request(url)
    with urllib.request.urlopen(req) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # A valid, non-empty zip with the usual single top-level directory.
        names = zf.namelist()
        assert names
        assert names[0].split("/")[0].startswith("getsentry-chartcuterie-")
