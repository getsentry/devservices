from __future__ import annotations

import sys
import threading
import time
from types import TracebackType


ANIMATION_FRAMES = ("⠟", "⠯", "⠷", "⠾", "⠽", "⠻")


class Status:
    """Shows loading status in the terminal."""

    def __init__(
        self, start_message: str | None = None, end_message: str | None = None
    ) -> None:
        self.start_message = start_message
        self.end_message = end_message
        self._stop_loading = threading.Event()
        self._loading_thread = threading.Thread(target=self._loading_animation)
        self._exception_occured = False

    def print(self, message: str) -> None:
        sys.stdout.write("\r" + message + "\n")
        sys.stdout.flush()

    def start(self) -> None:
        if self.start_message:
            print(self.start_message)
        self._loading_thread.start()

    def stop(self) -> None:
        self._stop_loading.set()
        self._loading_thread.join()
        sys.stdout.write("\r")
        sys.stdout.flush()
        if self.end_message and not self._exception_occured:
            print(self.end_message)

    def _loading_animation(self) -> None:
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
        self._exception_occured = exc_type is not None
        self.stop()
        if exc_type:
            if exc_type in (KeyboardInterrupt,):
                # Don't print anything if the user interrupts the process
                return True
            else:
                return False
        return False
