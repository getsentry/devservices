from __future__ import annotations

import pytest

from devservices.utils.state import State


@pytest.fixture(autouse=True)
def clear_singleton_instance() -> None:
    State._instance = None
