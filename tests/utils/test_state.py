from __future__ import annotations

from pathlib import Path
from unittest import mock

from devservices.utils.state import State


def test_state_simple(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_started_services() == []


def test_state_update_started_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
        assert state.get_started_services() == ["example-service"]
        assert state.get_active_modes_for_service("example-service") == ["default"]


def test_state_remove_started_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
        assert state.get_started_services() == ["example-service"]
        assert state.get_active_modes_for_service("example-service") == ["default"]
        state.remove_started_service("example-service")
        assert state.get_started_services() == []


def test_state_remove_unknown_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.remove_started_service("unknown-service")
        assert state.get_started_services() == []


def test_start_service_twice(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_started_service("example-service", "default")
        assert state.get_started_services() == ["example-service"]
        assert state.get_active_modes_for_service("example-service") == ["default"]
        state.update_started_service("example-service", "default")
        assert state.get_started_services() == ["example-service"]
        assert state.get_active_modes_for_service("example-service") == ["default"]


def test_get_mode_for_nonexistent_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_active_modes_for_service("unknown-service") == []
