from __future__ import annotations

from pathlib import Path
from unittest import mock

from devservices.utils.state import State
from devservices.utils.state import StateTables


def test_state_simple(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []


def test_state_update_service_entry(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "example-service"
        ]
        assert state.get_active_modes_for_service(
            "example-service", StateTables.STARTED_SERVICES
        ) == ["default"]


def test_state_remove_service_entry(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "example-service"
        ]
        assert state.get_active_modes_for_service(
            "example-service", StateTables.STARTED_SERVICES
        ) == ["default"]
        state.remove_service_entry("example-service", StateTables.STARTED_SERVICES)
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []


def test_state_remove_unknown_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.remove_service_entry("unknown-service", StateTables.STARTED_SERVICES)
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []


def test_start_service_twice(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "example-service"
        ]
        assert state.get_active_modes_for_service(
            "example-service", StateTables.STARTED_SERVICES
        ) == ["default"]
        state.update_service_entry(
            "example-service", "default", StateTables.STARTED_SERVICES
        )
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "example-service"
        ]
        assert state.get_active_modes_for_service(
            "example-service", StateTables.STARTED_SERVICES
        ) == ["default"]


def test_get_mode_for_nonexistent_service(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert (
            state.get_active_modes_for_service(
                "unknown-service", StateTables.STARTED_SERVICES
            )
            == []
        )
