"""Tests for tools/bump_version.py — semantic version bumping based on API changes."""

import pytest

from tools.bump_version import bump_major, bump_minor, compute_next_version
from tools.check_api_changes import ChangeKind


class TestBumpMajor:
    """Major version bumps."""

    def test_bump_major_from_0_1_0(self) -> None:
        assert bump_major("0.1.0") == "1.0.0"

    def test_bump_major_from_1_2_3(self) -> None:
        assert bump_major("1.2.3") == "2.0.0"

    def test_bump_major_resets_minor_and_patch(self) -> None:
        assert bump_major("3.5.7") == "4.0.0"


class TestBumpMinor:
    """Minor version bumps."""

    def test_bump_minor_from_0_1_0(self) -> None:
        assert bump_minor("0.1.0") == "0.2.0"

    def test_bump_minor_from_1_2_3(self) -> None:
        assert bump_minor("1.2.3") == "1.3.0"

    def test_bump_minor_resets_patch(self) -> None:
        assert bump_minor("2.5.9") == "2.6.0"


class TestComputeNextVersion:
    """Compute the next version based on change kind."""

    def test_breaking_bumps_major(self) -> None:
        assert compute_next_version("1.2.3", ChangeKind.BREAKING) == "2.0.0"

    def test_non_breaking_bumps_minor(self) -> None:
        assert compute_next_version("1.2.3", ChangeKind.NON_BREAKING) == "1.3.0"

    def test_no_change_returns_same(self) -> None:
        assert compute_next_version("1.2.3", ChangeKind.NONE) == "1.2.3"

    def test_breaking_from_zero(self) -> None:
        assert compute_next_version("0.1.0", ChangeKind.BREAKING) == "1.0.0"

    def test_non_breaking_from_zero(self) -> None:
        assert compute_next_version("0.1.0", ChangeKind.NON_BREAKING) == "0.2.0"
