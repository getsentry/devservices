from __future__ import annotations

import configparser
import http.client
import os
import socket
import subprocess
import time
import xmlrpc.client
from enum import IntEnum
from typing import TypedDict

from sentry_sdk import capture_exception
from supervisor.options import ServerOptions

from devservices.constants import DEVSERVICES_SUPERVISOR_CONFIG_DIR
from devservices.constants import SUPERVISOR_TIMEOUT
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


class SupervisorDaemonState(IntEnum):
    """
    Supervisor daemon states.

    https://supervisord.org/api.html#supervisor.rpcinterface.SupervisorNamespaceRPCInterface.getState
    """

    FATAL = 2
    RUNNING = 1
    RESTARTING = 0
    SHUTDOWN = -1


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


class ProcessInfo(TypedDict):
    """Status information for a supervisor process."""

    name: str
    state: int
    state_name: str
    description: str
    pid: int
    uptime: int
    start_time: int
    stop_time: int
    group: str


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

    def _wait_for_supervisor_ready(
        self, timeout: int = SUPERVISOR_TIMEOUT, interval: float = 0.5
    ) -> None:
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                client = self._get_rpc_client()
                state = client.supervisor.getState()
                # Unfortunately supervisor is untyped, so we need to assert the types
                assert isinstance(state, dict)
                assert "statecode" in state
                if state.get("statecode") == SupervisorDaemonState.RUNNING:
                    return
                time.sleep(interval)
            except (
                SupervisorConnectionError,
                socket.error,
                ConnectionRefusedError,
                xmlrpc.client.Fault,
            ):
                time.sleep(interval)

        raise SupervisorError(
            f"Supervisor didn't become ready within {timeout} seconds"
        )

    def start_supervisor_daemon(self) -> None:
        # Check if supervisor is already running by attempting to connect to it
        try:
            client = self._get_rpc_client()
            client.supervisor.getState()
            # Supervisor is already running, run supervisord update to update config and restart running processes
            # Notes:
            # - xmlrpc.client.reloadConfig does not work well here as config changes don't appear to be reloaded, so we use `supervisorctl update` instead
            # - processes that are edited/added will not be automatically started
            subprocess.run(
                ["supervisorctl", "-c", self.config_file_path, "update"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for supervisor to be ready after config reload
            self._wait_for_supervisor_ready()
            return
        except (xmlrpc.client.Fault, subprocess.CalledProcessError) as e:
            capture_exception(e, level="info")
            pass
        except (SupervisorConnectionError, socket.error, ConnectionRefusedError):
            # Supervisor is not running, so we need to start it
            pass

        try:
            subprocess.run(["supervisord", "-c", self.config_file_path], check=True)

            # Wait for supervisor to be ready after starting
            self._wait_for_supervisor_ready()
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

    def get_program_logs(self, program_name: str) -> str:
        """Get logs for a supervisor program as text output."""

        try:
            result = subprocess.run(
                [
                    "supervisorctl",
                    "-c",
                    self.config_file_path,
                    "tail",
                    program_name,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise SupervisorError(f"Failed to get logs for {program_name}: {str(e)}")

    def tail_program_logs(self, program_name: str) -> None:
        console = Console()

        if not self._is_program_running(program_name):
            console.info(f"Program {program_name} is not running")
            return

        try:
            # Use supervisorctl tail -f command to follow logs
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
            # Handle Ctrl+C gracefully when following logs
            pass

    def get_all_process_info(self) -> dict[str, ProcessInfo]:
        """Get status information for all supervisor programs."""
        # Check if supervisor client is up first, return empty list if down
        try:
            client = self._get_rpc_client()
            client.supervisor.getState()
        except (
            xmlrpc.client.Fault,
            SupervisorConnectionError,
            socket.error,
            ConnectionRefusedError,
        ):
            return {}

        try:
            all_process_info = client.supervisor.getAllProcessInfo()

            # Validate that the response is a list before iterating for typechecking
            if not isinstance(all_process_info, list):
                return {}

        except xmlrpc.client.Fault as e:
            raise SupervisorError(f"Failed to get programs status: {e.faultString}")

        processes_status: dict[str, ProcessInfo] = {}
        for process_info in all_process_info:
            if not isinstance(process_info, dict):
                continue

            # Extract basic fields with defaults
            name = process_info.get("name", "")
            state = process_info.get("state", SupervisorProcessState.UNKNOWN)
            state_name = SupervisorProcessState(state).name
            description = process_info.get("description", "")
            pid = process_info.get("pid", 0)
            group = process_info.get("group", "")

            # Calculate uptime for running processes
            start_time = process_info.get("start", 0)
            now = process_info.get("now", 0)
            uptime = max(0, now - start_time) if start_time > 0 and now > 0 else 0

            program_status: ProcessInfo = {
                "name": name,
                "state": state,
                "state_name": state_name,
                "description": description,
                "pid": pid,
                "uptime": uptime,
                "start_time": start_time,
                "stop_time": process_info.get("stop", 0),
                "group": group,
            }
            processes_status[name] = program_status

        return processes_status
