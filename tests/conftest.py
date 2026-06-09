from __future__ import annotations

import pytest

from devservices.utils.state import State


@pytest.fixture(autouse=True)
def clear_singleton_instance() -> None:
    State._instance = None


@pytest.fixture(autouse=True)
def deterministic_github_auth(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep GitHub token resolution deterministic and offline.

    Without this, any test that fetches a dependency would consult the ambient
    GITHUB_TOKEN/GH_TOKEN env vars and shell out to the real `gh` CLI, which is
    slow and varies between local and CI environments. Tests that exercise the
    auth logic itself override these patches.

    Integration tests opt out so they can authenticate against real GitHub.
    """
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("devservices.utils.github.shutil.which", lambda _: None)
    # Treat the warning as already emitted so unauthenticated fetches stay quiet.
    monkeypatch.setattr("devservices.utils.github._auth_warned", True)
