from __future__ import annotations

import sqlite3

from devservices.constants import DB_FILE


class State:
    _instance: State | None = None
    db_file: str
    conn: sqlite3.Connection

    def __new__(cls) -> State:
        if cls._instance is None:
            cls._instance = super(State, cls).__new__(cls)
            cls._instance.db_file = DB_FILE
            cls._instance.conn = sqlite3.connect(cls._instance.db_file)
            cls._instance.initialize_database()
        return cls._instance

    def initialize_database(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS started_services (
                service_name TEXT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        self.conn.commit()

    def get_connection(self) -> sqlite3.Connection:
        return self.conn

    def add_started_service(self, service_name: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO started_services (service_name) VALUES (?)
        """,
            (service_name,),
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
