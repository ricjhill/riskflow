"""Benchmark test configuration.

Automatically applies the benchmark marker to all tests in this directory.
Provides the shared Timer context manager used by guardrail tests.
"""

import time

import pytest


class Timer:
    """Measure wall-clock time for a code block.

    Usage::

        with Timer() as t:
            some_function()
        assert t.elapsed_ms < 50, f"Took {t.elapsed_ms:.1f}ms (budget: 50ms)"
    """

    def __init__(self) -> None:
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add 'benchmark' marker to all tests in this directory."""
    for item in items:
        if "/benchmark/" in str(item.fspath):
            item.add_marker(pytest.mark.benchmark)
