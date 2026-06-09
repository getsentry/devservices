from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from devservices.utils.console import Console

GITHUB_API_ACCEPT = "application/vnd.github+json"

_auth_warning_lock = threading.Lock()
_auth_warned = False


def parse_repo_path(repo_link: str) -> str:
    """Extract the "owner/repo" path from a GitHub URL."""
    url = repo_link.rstrip("/").removesuffix(".git")
    if "github.com/" not in url:
        raise ValueError(f"Not a GitHub URL: {repo_link}")
    return url.split("github.com/", 1)[1]


def zipball_url(repo_path: str, ref: str) -> str:
    return f"https://api.github.com/repos/{repo_path}/zipball/{ref}"


def api_headers() -> dict[str, str]:
    """Build request headers for the GitHub API, authenticating when possible.

    Authenticated requests get the 5000 req/hr rate limit instead of the 60
    req/hr unauthenticated limit (which CI runners, sharing egress IPs, exhaust
    quickly and then receive HTTP 403s).
    """
    headers = {"Accept": GITHUB_API_ACCEPT}
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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
