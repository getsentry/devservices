from __future__ import annotations

from pathlib import Path
from unittest import mock

from devservices.utils.state import State


def test_state_simple(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_started_services() == []


def test_state_add_started_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_started_service("example-service")
        assert state.get_started_services() == ["example-service"]


def test_state_remove_started_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_started_service("example-service")
        assert state.get_started_services() == ["example-service"]
        state.remove_started_service("example-service")
        assert state.get_started_services() == []


def test_state_remove_unknown_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.DB_FILE", str(tmp_path / "state")):
        state = State()
        state.remove_started_service("unknown-service")
        assert state.get_started_services() == []
