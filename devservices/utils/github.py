from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import urllib.request

from devservices.utils.console import Console

GITHUB_API_ACCEPT = "application/vnd.github+json"

_auth_warning_lock = threading.Lock()
_auth_warned = False


def parse_repo_path(repo_link: str) -> str:
    """Extract the "owner/repo" path from a GitHub URL.

    Handles both HTTPS (https://github.com/owner/repo) and SSH
    (git@github.com:owner/repo) formats.
    """
    url = repo_link.rstrip("/").removesuffix(".git")
    if "github.com/" in url:
        return url.split("github.com/", 1)[1]
    if "github.com:" in url:
        return url.split("github.com:", 1)[1]
    raise ValueError(f"Not a GitHub URL: {repo_link}")


def zipball_url(repo_path: str, ref: str) -> str:
    return f"https://api.github.com/repos/{repo_path}/zipball/{ref}"


def build_api_request(url: str) -> urllib.request.Request:
    """Build an authenticated GitHub API request, authenticating when possible.

    Authenticated requests get the 5000 req/hr rate limit instead of the 60
    req/hr unauthenticated limit (which CI runners, sharing egress IPs, exhaust
    quickly and then receive HTTP 403s).
    """
    req = urllib.request.Request(url, headers={"Accept": GITHUB_API_ACCEPT})
    token = _get_token()
    if token:
        # Use an unredirected header so the token is only sent to api.github.com
        # and is NOT forwarded when the API 302-redirects the download to
        # codeload.github.com (and S3-backed hosts for other endpoints), which
        # reject or mishandle requests that carry an Authorization header.
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def _get_token() -> str | None:
    # Prefer an explicit token from the environment (CI sets these), otherwise
    # fall back to the locally authenticated `gh` CLI so local users are authed
    # without extra setup.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    if shutil.which("gh") is not None:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            token = result.stdout.strip()
            if token:
                return token
    _warn_unauthenticated()
    return None


def _warn_unauthenticated() -> None:
    # Fetches run concurrently across dependencies; only warn once per process so
    # we don't spam the same message for every dependency.
    global _auth_warned
    with _auth_warning_lock:
        if _auth_warned:
            return
        _auth_warned = True
    if sys.platform == "darwin":
        install_hint = "Install the GitHub CLI (brew install gh)"
    else:
        install_hint = "Install the GitHub CLI (https://github.com/cli/cli)"
    Console().warning(
        "Could not authenticate with GitHub; falling back to unauthenticated "
        f"downloads, which are heavily rate-limited. {install_hint} and run "
        "`gh auth login` to authenticate."
    )
