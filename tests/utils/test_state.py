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


# -- Sandbox state tests --


def test_add_sandbox_instance(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance(
            "sandbox-test",
            "my-project",
            "us-central1-a",
            "e2-standard-8",
            "main",
            "default",
        )
        instance = state.get_sandbox_instance("sandbox-test")
        assert instance is not None
        assert instance["name"] == "sandbox-test"
        assert instance["project"] == "my-project"
        assert instance["zone"] == "us-central1-a"
        assert instance["machine_type"] == "e2-standard-8"
        assert instance["branch"] == "main"
        assert instance["mode"] == "default"
        assert instance["status"] == "CREATING"


def test_get_sandbox_instance_not_found(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_sandbox_instance("nonexistent") is None


def test_get_sandbox_instances_empty(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_sandbox_instances() == []


def test_get_sandbox_instances_multiple(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance("sandbox-a", "proj", "zone-a", "e2-standard-4")
        state.add_sandbox_instance("sandbox-b", "proj", "zone-b", "e2-standard-8")
        instances = state.get_sandbox_instances()
        assert len(instances) == 2
        names = [i["name"] for i in instances]
        assert "sandbox-a" in names
        assert "sandbox-b" in names


def test_update_sandbox_status(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance("sandbox-test", "proj", "zone", "e2-standard-8")
        inst = state.get_sandbox_instance("sandbox-test")
        assert inst is not None
        assert inst["status"] == "CREATING"
        state.update_sandbox_status("sandbox-test", "RUNNING")
        inst = state.get_sandbox_instance("sandbox-test")
        assert inst is not None
        assert inst["status"] == "RUNNING"
        state.update_sandbox_status("sandbox-test", "TERMINATED")
        inst = state.get_sandbox_instance("sandbox-test")
        assert inst is not None
        assert inst["status"] == "TERMINATED"


def test_remove_sandbox_instance(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance("sandbox-test", "proj", "zone", "e2-standard-8")
        assert state.get_sandbox_instance("sandbox-test") is not None
        state.remove_sandbox_instance("sandbox-test")
        assert state.get_sandbox_instance("sandbox-test") is None


def test_get_default_sandbox(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance("sandbox-old", "proj", "zone", "e2-standard-8")
        state.add_sandbox_instance("sandbox-new", "proj", "zone", "e2-standard-8")
        # Ensure distinct timestamps so ORDER BY created_at DESC is deterministic
        cursor = state.conn.cursor()
        cursor.execute(
            "UPDATE sandbox_instances SET created_at = '2020-01-01' WHERE name = 'sandbox-old'"
        )
        state.conn.commit()
        # Most recently created should be default
        default = state.get_default_sandbox()
        assert default == "sandbox-new"


def test_get_default_sandbox_empty(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        assert state.get_default_sandbox() is None


def test_clear_state_includes_sandbox(tmp_path: Path) -> None:
    with mock.patch("devservices.utils.state.STATE_DB_FILE", str(tmp_path / "state")):
        state = State()
        state.add_sandbox_instance("sandbox-test", "proj", "zone", "e2-standard-8")
        assert len(state.get_sandbox_instances()) == 1
        state.clear_state()
        assert len(state.get_sandbox_instances()) == 0
