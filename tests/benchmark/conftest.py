"""Benchmark test configuration.

Automatically applies the benchmark marker to all tests in this directory.
"""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add 'benchmark' marker to all tests in this directory."""
    for item in items:
        if "/benchmark/" in str(item.fspath):
            item.add_marker(pytest.mark.benchmark)
