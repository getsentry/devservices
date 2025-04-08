from __future__ import annotations

import os
import subprocess
import xmlrpc.client

from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorConnectionError
from devservices.exceptions import SupervisorError
from devservices.exceptions import SupervisorProcessError


class SupervisorManager:
    def __init__(self, port: int | None, config_file: str | None = None) -> None:
        if port is None:
            raise SupervisorConfigError("Port is required")
        if config_file is None or not os.path.exists(config_file):
            raise SupervisorConfigError("Supervisor config file not provided")

        self.config_file = config_file
        self.port = port

    def _get_rpc_client(self) -> xmlrpc.client.ServerProxy:
        """Get or create an XML-RPC client that connects to the supervisor daemon."""
        try:
            return xmlrpc.client.ServerProxy(f"http://localhost:{self.port}/RPC2")
        except xmlrpc.client.Fault as e:
            raise SupervisorConnectionError(
                f"Failed to connect to supervisor XML-RPC server: {e.faultString}"
            )
        except xmlrpc.client.ProtocolError as e:
            raise SupervisorConnectionError(
                f"Failed to connect to supervisor XML-RPC server: {e.errmsg}"
            )

    def start_supervisor_daemon(self) -> None:
        try:
            subprocess.run(["supervisord", "-c", self.config_file], check=True)
        except subprocess.CalledProcessError as e:
            raise SupervisorError(f"Failed to start supervisor: {str(e)}")
        except FileNotFoundError:
            raise SupervisorError(
                "supervisord command not found. Is supervisor installed?"
            )

    def stop_supervisor_daemon(self) -> None:
        try:
            self._get_rpc_client().supervisor.shutdown()
        except xmlrpc.client.Fault as e:
            raise SupervisorError(f"Failed to stop supervisor: {e.faultString}")

    def start_program(self, program_name: str) -> None:
        try:
            self._get_rpc_client().supervisor.startProcess(program_name)
        except xmlrpc.client.Fault as e:
            raise SupervisorProcessError(
                f"Failed to start program {program_name}: {e.faultString}"
            )

    def stop_program(self, program_name: str) -> None:
        try:
            self._get_rpc_client().supervisor.stopProcess(program_name)
        except xmlrpc.client.Fault as e:
            raise SupervisorProcessError(
                f"Failed to stop program {program_name}: {e.faultString}"
            )
