"""Contract test configuration.

Automatically applies the contract marker to all tests in this directory.
"""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add 'contract' marker to all tests in this directory."""
    for item in items:
        if "/contract/" in str(item.fspath):
            item.add_marker(pytest.mark.contract)
