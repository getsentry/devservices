from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from types import TracebackType

from devservices.constants import Color


ANIMATION_FRAMES = ("⠟", "⠯", "⠷", "⠾", "⠽", "⠻")


class Console:
    _instance: Console | None = None

    def __new__(cls) -> Console:
        if cls._instance is None:
            cls._instance = super(Console, cls).__new__(cls)
        return cls._instance

    def print(self, message: str, color: str = "", bold: bool = False) -> None:
        color = color + (Color.BOLD if bold else "")
        end = Color.RESET if color != "" or bold else ""
        sys.stdout.write(color + message + end + "\n")
        sys.stdout.flush()

    def success(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.GREEN, bold=bold)

    def failure(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.RED, bold=bold)

    def warning(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.YELLOW, bold=bold)

    def info(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color="", bold=bold)

    def confirm(self, message: str) -> bool:
        self.warning(message=message, bold=True)
        response = input("(Y/n): ").strip().lower()
        return response in ("y", "yes", "")


class Status:
    """Shows loading status in the terminal."""

    def __init__(
        self,
        on_start: Callable[[], None] | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self.on_start = on_start
        self.on_success = on_success
        self._stop_loading = threading.Event()
        self._loading_thread = threading.Thread(target=self._loading_animation)
        self._exception_occurred = False
        self.console = Console()

    def print(self, message: str, color: str = "", bold: bool = False) -> None:
        self.console.print("\r" + message, color=color, bold=bold)

    def success(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.GREEN, bold=bold)

    def failure(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.RED, bold=bold)

    def warning(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color=Color.YELLOW, bold=bold)

    def info(self, message: str, bold: bool = False) -> None:
        self.print(message=message, color="", bold=bold)

    def start(self) -> None:
        if self.on_start:
            self.on_start()
        self._loading_thread.start()

    def stop(self) -> None:
        self._stop_loading.set()
        self._loading_thread.join()
        sys.stdout.write("\r")
        sys.stdout.flush()
        if self.on_success and not self._exception_occurred:
            self.on_success()

    def _loading_animation(self) -> None:
        if os.environ.get("CI", default="false") == "true":
            return
        idx = 0
        while not self._stop_loading.is_set():
            sys.stdout.write("\r" + ANIMATION_FRAMES[idx % len(ANIMATION_FRAMES)] + " ")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)

    def __enter__(self) -> Status:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_inst: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self._exception_occurred = exc_type is not None
        self.stop()
        if exc_type:
            if exc_type in (KeyboardInterrupt,):
                # Don't print anything if the user interrupts the process
                return True
            else:
                return False
        return False
