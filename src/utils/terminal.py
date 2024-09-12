from __future__ import annotations

import sys
import threading
import time
from types import TracebackType
from typing import Type


ANIMATION_FRAMES = ["⠁", "⠃", "⠇", "⠏", "⠟", "⠿"]


class Status:
    """Shows loading status in the terminal."""

    def __init__(self, start_message: str | None) -> None:
        self.start_message = start_message
        self._stop_loading = threading.Event()
        self._loading_thread = threading.Thread(target=self._loading_animation)

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
        exc_type: Type[BaseException] | None,
        exc_inst: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self.stop()
        if exc_type:
            print(f"An error occurred: {exc_inst}")
            return True
        return False
