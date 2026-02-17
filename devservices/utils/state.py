from __future__ import annotations

import os
import sqlite3
from enum import Enum
from enum import StrEnum
from typing import Literal

from devservices.constants import DEVSERVICES_LOCAL_DIR
from devservices.constants import STATE_DB_FILE


class ServiceRuntime(StrEnum):
    LOCAL = "local"
    CONTAINERIZED = "containerized"


class StateTables(Enum):
    STARTED_SERVICES = "started_services"
    STARTING_SERVICES = "starting_services"
    SERVICE_RUNTIME = "service_runtime"
    SANDBOX_INSTANCES = "sandbox_instances"


class State:
    _instance: State | None = None
    state_db_file: str
    conn: sqlite3.Connection

    def __new__(cls) -> State:
        if cls._instance is None:
            cls._instance = super(State, cls).__new__(cls)
            if not os.path.exists(DEVSERVICES_LOCAL_DIR):
                os.makedirs(DEVSERVICES_LOCAL_DIR)
            cls._instance.state_db_file = STATE_DB_FILE
            cls._instance.conn = sqlite3.connect(cls._instance.state_db_file)
            cls._instance.initialize_database()
        return cls._instance

    def initialize_database(self) -> None:
        cursor = self.conn.cursor()
        # Formatted strings here and throughout the file should be extremely low risk given these are constants
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {StateTables.STARTED_SERVICES.value} (
                service_name TEXT PRIMARY KEY,
                mode TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {StateTables.STARTING_SERVICES.value} (
                service_name TEXT PRIMARY KEY,
                mode TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {StateTables.SERVICE_RUNTIME.value} (
                service_name TEXT PRIMARY KEY,
                runtime TEXT
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {StateTables.SANDBOX_INSTANCES.value} (
                name TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                zone TEXT NOT NULL,
                machine_type TEXT NOT NULL,
                branch TEXT DEFAULT 'master',
                mode TEXT DEFAULT 'default',
                status TEXT DEFAULT 'CREATING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        self.conn.commit()

    def update_service_entry(
        self,
        service_name: str,
        mode: str,
        table: (
            Literal[StateTables.STARTED_SERVICES]
            | Literal[StateTables.STARTING_SERVICES]
        ),
    ) -> None:
        cursor = self.conn.cursor()
        service_entries = self.get_service_entries(table)
        active_modes = self.get_active_modes_for_service(service_name, table)
        if service_name in service_entries and mode in active_modes:
            return
        if service_name in service_entries:
            cursor.execute(
                f"""
                UPDATE {table.value} SET mode = ? WHERE service_name = ?
            """,
                (",".join(active_modes + [mode]), service_name),
            )
        else:
            cursor.execute(
                f"""
                INSERT INTO {table.value} (service_name, mode) VALUES (?, ?)
            """,
                (service_name, ",".join(active_modes + [mode])),
            )
        self.conn.commit()

    def remove_service_entry(self, service_name: str, table: StateTables) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM {table.value} WHERE service_name = ?
        """,
            (service_name,),
        )
        self.conn.commit()

    def get_service_entries(self, table: StateTables) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT service_name FROM {table.value}
        """
        )
        return [row[0] for row in cursor.fetchall()]

    def get_active_modes_for_service(
        self,
        service_name: str,
        table: (
            Literal[StateTables.STARTED_SERVICES]
            | Literal[StateTables.STARTING_SERVICES]
        ),
    ) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT mode FROM {table.value} WHERE service_name = ?
        """,
            (service_name,),
        )
        result = cursor.fetchone()
        if result is None:
            return []
        return str(result[0]).split(",")

    def get_service_runtime(self, service_name: str) -> ServiceRuntime:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT runtime FROM {StateTables.SERVICE_RUNTIME.value} WHERE service_name = ?
        """,
            (service_name,),
        )
        result = cursor.fetchone()
        if result is None:
            return ServiceRuntime.CONTAINERIZED
        return ServiceRuntime(result[0])

    def update_service_runtime(
        self, service_name: str, runtime: ServiceRuntime
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            INSERT OR REPLACE INTO {StateTables.SERVICE_RUNTIME.value} (service_name, runtime) VALUES (?, ?)
        """,
            (service_name, runtime),
        )
        self.conn.commit()

    def get_services_by_runtime(self, runtime: ServiceRuntime) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT service_name FROM {StateTables.SERVICE_RUNTIME.value} WHERE runtime = ?
        """,
            (runtime,),
        )
        return [row[0] for row in cursor.fetchall()]

    def remove_stale_service_entry(self, service_name: str) -> None:
        """Remove a service from all state tables.

        Used to clean up entries for services that no longer exist on disk.
        """
        self.remove_service_entry(service_name, StateTables.STARTING_SERVICES)
        self.remove_service_entry(service_name, StateTables.STARTED_SERVICES)
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM {StateTables.SERVICE_RUNTIME.value} WHERE service_name = ?
        """,
            (service_name,),
        )
        self.conn.commit()

    def add_sandbox_instance(
        self,
        name: str,
        project: str,
        zone: str,
        machine_type: str,
        branch: str = "master",
        mode: str = "default",
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO {StateTables.SANDBOX_INSTANCES.value}
            (name, project, zone, machine_type, branch, mode)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (name, project, zone, machine_type, branch, mode),
        )
        self.conn.commit()

    def get_sandbox_instance(self, name: str) -> dict[str, str] | None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT name, project, zone, machine_type, branch, mode, status, created_at
            FROM {StateTables.SANDBOX_INSTANCES.value} WHERE name = ?
        """,
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "project": row[1],
            "zone": row[2],
            "machine_type": row[3],
            "branch": row[4],
            "mode": row[5],
            "status": row[6],
            "created_at": row[7],
        }

    def get_sandbox_instances(self) -> list[dict[str, str]]:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT name, project, zone, machine_type, branch, mode, status, created_at
            FROM {StateTables.SANDBOX_INSTANCES.value}
            ORDER BY created_at DESC
        """
        )
        rows = cursor.fetchall()
        return [
            {
                "name": row[0],
                "project": row[1],
                "zone": row[2],
                "machine_type": row[3],
                "branch": row[4],
                "mode": row[5],
                "status": row[6],
                "created_at": row[7],
            }
            for row in rows
        ]

    def update_sandbox_status(self, name: str, status: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            UPDATE {StateTables.SANDBOX_INSTANCES.value} SET status = ? WHERE name = ?
        """,
            (status, name),
        )
        self.conn.commit()

    def remove_sandbox_instance(self, name: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM {StateTables.SANDBOX_INSTANCES.value} WHERE name = ?
        """,
            (name,),
        )
        self.conn.commit()

    def get_default_sandbox(self) -> str | None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            SELECT name FROM {StateTables.SANDBOX_INSTANCES.value}
            ORDER BY created_at DESC LIMIT 1
        """
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def clear_state(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM {StateTables.STARTED_SERVICES.value}
        """
        )
        cursor.execute(
            f"""
            DELETE FROM {StateTables.STARTING_SERVICES.value}
        """
        )
        cursor.execute(
            f"""
            DELETE FROM {StateTables.SERVICE_RUNTIME.value}
        """
        )
        cursor.execute(
            f"""
            DELETE FROM {StateTables.SANDBOX_INSTANCES.value}
        """
        )
        self.conn.commit()
