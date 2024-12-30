from __future__ import annotations

import contextlib
import fcntl
from collections.abc import Generator


@contextlib.contextmanager
def lock(path: str) -> Generator[None, None, None]:
    with open(path, mode="a+", encoding="utf-8") as f:
        with _locked(f.fileno()):
            yield


@contextlib.contextmanager
def _locked(fileno: int) -> Generator[None, None, None]:
    try:
        fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fcntl.flock(fileno, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fileno, fcntl.LOCK_UN)
