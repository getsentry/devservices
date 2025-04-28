from __future__ import annotations

import configparser
import http.client
import os
import socket
import subprocess
import xmlrpc.client
from enum import IntEnum

from supervisor.options import ServerOptions

from devservices.constants import DEVSERVICES_SUPERVISOR_CONFIG_DIR
from devservices.exceptions import SupervisorConfigError
from devservices.exceptions import SupervisorConnectionError
from devservices.exceptions import SupervisorError
from devservices.exceptions import SupervisorProcessError
from devservices.utils.console import Console


class SupervisorProcessState(IntEnum):
    """
    Supervisor process states.

    https://supervisord.org/subprocess.html#process-states
    """

    STOPPED = 0
    STARTING = 10
    RUNNING = 20
    BACKOFF = 30
    STOPPING = 40
    EXITED = 100
    FATAL = 200
    UNKNOWN = 1000


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTP connection over Unix sockets."""

    def __init__(self, path: str) -> None:
        super().__init__("localhost")
        self.unix_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.unix_path)


class UnixSocketTransport(xmlrpc.client.Transport):
    """Transport for XML-RPC over Unix sockets. Interfaces between the XML-RPC client and the HTTP connection over Unix sockets."""

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self.socket_path = socket_path

    def make_connection(
        self, host: str | tuple[str, dict[str, str]]
    ) -> UnixSocketHTTPConnection:
        return UnixSocketHTTPConnection(self.socket_path)


class SupervisorManager:
    def __init__(self, config_file_path: str, service_name: str) -> None:
        self.service_name = service_name
        if not os.path.exists(config_file_path):
            raise SupervisorConfigError(
                f"Config file {config_file_path} does not exist"
            )
        self.socket_path = os.path.join(
            DEVSERVICES_SUPERVISOR_CONFIG_DIR, f"{service_name}.sock"
        )
        self.config_file_path = self._extend_config_file(config_file_path)

    def _extend_config_file(self, config_file_path: str) -> str:
        """Extend the supervisor config file passed into devservices with configuration settings that should be abstracted from users."""

        config = configparser.ConfigParser()

        config.read(config_file_path)
        os.makedirs(DEVSERVICES_SUPERVISOR_CONFIG_DIR, exist_ok=True)

        # Set unix http server to use the socket path
        config["unix_http_server"] = {"file": self.socket_path}

        # Set generated pidfile to use service name
        config["supervisord"] = {
            "pidfile": os.path.join(
                DEVSERVICES_SUPERVISOR_CONFIG_DIR, f"{self.service_name}.pid"
            )
        }

        # Set supervisorctl to use the socket path
        config["supervisorctl"] = {"serverurl": f"unix://{self.socket_path}"}

        # Required by supervisor to work properly
        config["rpcinterface:supervisor"] = {
            "supervisor.rpcinterface_factory": "supervisor.rpcinterface:make_main_rpcinterface"
        }

        extended_config_file_path = os.path.join(
            DEVSERVICES_SUPERVISOR_CONFIG_DIR, f"{self.service_name}.processes.conf"
        )
        with open(extended_config_file_path, "w") as f:
            config.write(f)

        return extended_config_file_path

    def _get_rpc_client(self) -> xmlrpc.client.ServerProxy:
        """Get or create an XML-RPC client that connects to the supervisor daemon."""
        try:
            # The URI is not used, but is required arg by xmlrpc.client.ServerProxy
            return xmlrpc.client.ServerProxy(
                "http://localhost", transport=UnixSocketTransport(self.socket_path)
            )
        except xmlrpc.client.Fault as e:
            raise SupervisorConnectionError(
                f"Failed to connect to supervisor XML-RPC server: {e.faultString}"
            )
        except xmlrpc.client.ProtocolError as e:
            raise SupervisorConnectionError(
                f"Failed to connect to supervisor XML-RPC server: {e.errmsg}"
            )

    def _is_program_running(self, program_name: str) -> bool:
        try:
            client = self._get_rpc_client()
            process_info = client.supervisor.getProcessInfo(program_name)
            if not isinstance(process_info, dict):
                return False

            state = process_info.get("state")
            if not isinstance(state, int):
                return False
            return state == SupervisorProcessState.RUNNING
        except xmlrpc.client.Fault:
            # If we can't get the process info, assume it's not running
            return False

    def start_supervisor_daemon(self) -> None:
        try:
            subprocess.run(["supervisord", "-c", self.config_file_path], check=True)
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

    def start_process(self, name: str) -> None:
        if self._is_program_running(name):
            return
        try:
            self._get_rpc_client().supervisor.startProcess(name)
        except xmlrpc.client.Fault as e:
            raise SupervisorProcessError(
                f"Failed to start process {name}: {e.faultString}"
            )

    def stop_process(self, name: str) -> None:
        if not self._is_program_running(name):
            return
        try:
            self._get_rpc_client().supervisor.stopProcess(name)
        except xmlrpc.client.Fault as e:
            raise SupervisorProcessError(
                f"Failed to stop process {name}: {e.faultString}"
            )

    def get_program_command(self, program_name: str) -> str:
        opts = ServerOptions()
        opts.configfile = self.config_file_path
        opts.process_config()
        for group in opts.process_group_configs:
            for proc in group.process_configs:
                if proc.name == program_name and isinstance(proc.command, str):
                    return proc.command
        raise SupervisorConfigError(f"Program {program_name} not found in config")

    def tail_program_logs(self, program_name: str) -> None:
        if not self._is_program_running(program_name):
            console = Console()
            console.failure(f"Program {program_name} is not running")
            return

        try:
            # Use supervisorctl tail command
            subprocess.run(
                [
                    "supervisorctl",
                    "-c",
                    self.config_file_path,
                    "tail",
                    "-f",
                    program_name,
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise SupervisorError(f"Failed to tail logs for {program_name}: {str(e)}")
        except KeyboardInterrupt:
            pass
