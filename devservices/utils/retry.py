from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[BaseException, int], None] | None = None,
) -> T:
    """
    Call fn() up to `retries` times, sleeping `delay` seconds between attempts.
    Raises the last exception if all attempts fail.

    Args:
        fn: Callable to invoke.
        retries: Total number of attempts (must be >= 1).
        delay: Seconds to sleep between attempts.
        exceptions: Exception types that trigger a retry.
        on_retry: Optional callback(exc, attempts_remaining) invoked before each sleep.
    """
    if retries < 1:
        raise ValueError("retries must be >= 1")
    for attempt in range(retries):
        try:
            return fn()
        except exceptions as e:
            if attempt == retries - 1:
                raise
            if on_retry is not None:
                on_retry(e, retries - attempt - 1)
            time.sleep(delay)
    raise AssertionError("unreachable")
