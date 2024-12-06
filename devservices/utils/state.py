from __future__ import annotations

import os
import sqlite3

from devservices.constants import DEVSERVICES_LOCAL_DIR
from devservices.constants import STATE_DB_FILE


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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS started_services (
                service_name TEXT PRIMARY KEY,
                mode TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        self.conn.commit()

    def update_started_service(self, service_name: str, mode: str) -> None:
        cursor = self.conn.cursor()
        started_services = self.get_started_services()
        active_modes = self.get_active_modes_for_service(service_name)
        if service_name in started_services and mode in active_modes:
            return
        if service_name in started_services:
            cursor.execute(
                """
                UPDATE started_services SET mode = ? WHERE service_name = ?
            """,
                (",".join(active_modes + [mode]), service_name),
            )
        else:
            cursor.execute(
                """
                INSERT INTO started_services (service_name, mode) VALUES (?, ?)
            """,
                (service_name, ",".join(active_modes + [mode])),
            )
        self.conn.commit()

    def remove_started_service(self, service_name: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM started_services WHERE service_name = ?
        """,
            (service_name,),
        )
        self.conn.commit()

    def get_started_services(self) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT service_name FROM started_services
        """
        )
        return [row[0] for row in cursor.fetchall()]

    def get_active_modes_for_service(self, service_name: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT mode FROM started_services WHERE service_name = ?
        """,
            (service_name,),
        )
        result = cursor.fetchone()
        if result is None:
            return []
        return str(result[0]).split(",")

    def clear_state(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM started_services
        """
        )
        self.conn.commit()
