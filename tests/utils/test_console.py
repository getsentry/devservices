from __future__ import annotations

import io
from unittest import mock

from devservices.utils.console import Console


def test_console_print_swallows_broken_pipe() -> None:
    """Console.print must not propagate BrokenPipeError (e.g. when piping to a
    downstream process that closed its end of the pipe)."""
    console = Console()
    fake_stdout = mock.Mock(spec=io.StringIO)
    fake_stdout.write.side_effect = BrokenPipeError()

    with mock.patch("devservices.utils.console.sys.stdout", fake_stdout):
        console.print("hello")
        console.success("success")
        console.failure("failure")
        console.warning("warning")
        console.info("info")

    # write was attempted each call but the BrokenPipeError was swallowed
    assert fake_stdout.write.call_count == 5
