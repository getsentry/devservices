from __future__ import annotations

from pathlib import Path
from unittest import mock

from devservices.utils.state import ServiceRuntime
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


def test_get_and_update_service_runtime(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_runtime("example-service", ServiceRuntime.CONTAINERIZED)
        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )
        state.update_service_runtime("example-service", ServiceRuntime.LOCAL)
        assert state.get_service_runtime("example-service") == ServiceRuntime.LOCAL
        state.update_service_runtime("example-service", ServiceRuntime.CONTAINERIZED)
        assert (
            state.get_service_runtime("example-service") == ServiceRuntime.CONTAINERIZED
        )


def test_get_service_runtime_defaults_to_containerized(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert (
            state.get_service_runtime("unknown-service") == ServiceRuntime.CONTAINERIZED
        )


def test_get_services_by_runtime(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_services_by_runtime(ServiceRuntime.CONTAINERIZED) == []
        assert state.get_services_by_runtime(ServiceRuntime.LOCAL) == []
        state.update_service_runtime("first-service", ServiceRuntime.CONTAINERIZED)
        state.update_service_runtime("second-service", ServiceRuntime.LOCAL)
        state.update_service_runtime("third-service", ServiceRuntime.CONTAINERIZED)
        assert state.get_services_by_runtime(ServiceRuntime.CONTAINERIZED) == [
            "first-service",
            "third-service",
        ]
        assert state.get_services_by_runtime(ServiceRuntime.LOCAL) == ["second-service"]

        state.update_service_runtime("first-service", ServiceRuntime.LOCAL)
        assert state.get_services_by_runtime(ServiceRuntime.CONTAINERIZED) == [
            "third-service"
        ]
        assert state.get_services_by_runtime(ServiceRuntime.LOCAL) == [
            "second-service",
            "first-service",
        ]


def test_clear_state(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.update_service_entry(
            "first-service", "default", StateTables.STARTED_SERVICES
        )
        state.update_service_entry(
            "second-service", "default", StateTables.STARTING_SERVICES
        )
        state.update_service_runtime("first-service", ServiceRuntime.CONTAINERIZED)
        state.update_service_runtime("second-service", ServiceRuntime.LOCAL)
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == [
            "first-service"
        ]
        assert state.get_service_entries(StateTables.STARTING_SERVICES) == [
            "second-service"
        ]
        assert state.get_services_by_runtime(ServiceRuntime.CONTAINERIZED) == [
            "first-service"
        ]
        assert state.get_services_by_runtime(ServiceRuntime.LOCAL) == ["second-service"]
        state.clear_state()
        assert state.get_service_entries(StateTables.STARTED_SERVICES) == []
        assert state.get_service_entries(StateTables.STARTING_SERVICES) == []
        assert state.get_services_by_runtime(ServiceRuntime.CONTAINERIZED) == []
        assert state.get_services_by_runtime(ServiceRuntime.LOCAL) == []
