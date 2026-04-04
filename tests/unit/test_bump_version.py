"""Tests for tools/bump_version.py — semantic version bumping based on API changes."""

from pathlib import Path

import pytest

from tools.bump_version import (
    bump_major,
    bump_minor,
    compute_next_version,
    read_version,
    write_version,
)
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


class TestBumpInvalidInput:
    """Invalid version strings."""

    def test_bump_major_two_parts(self) -> None:
        with pytest.raises(ValueError):
            bump_major("1.0")

    def test_bump_minor_two_parts(self) -> None:
        with pytest.raises(ValueError):
            bump_minor("1.0")

    def test_bump_major_empty_string(self) -> None:
        with pytest.raises(ValueError):
            bump_major("")

    def test_bump_minor_empty_string(self) -> None:
        with pytest.raises(ValueError):
            bump_minor("")


class TestReadVersion:
    """Read version from pyproject.toml."""

    def test_reads_current_version(self) -> None:
        version = read_version()
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_raises_on_missing_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_pyproject = tmp_path / "pyproject.toml"
        fake_pyproject.write_text("[project]\nname = 'test'\n")
        monkeypatch.setattr("tools.bump_version.PYPROJECT", fake_pyproject)
        with pytest.raises(ValueError, match="version"):
            read_version()


class TestWriteVersion:
    """Write version to pyproject.toml."""

    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pyproject = tmp_path / "pyproject.toml"
        fake_pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')
        monkeypatch.setattr("tools.bump_version.PYPROJECT", fake_pyproject)
        write_version("2.0.0")
        assert read_version() == "2.0.0"

    def test_preserves_other_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        content = (
            '[project]\nname = "test"\nversion = "1.0.0"\n\n[tool.ruff]\ntarget-version = "py312"\n'
        )
        fake_pyproject = tmp_path / "pyproject.toml"
        fake_pyproject.write_text(content)
        monkeypatch.setattr("tools.bump_version.PYPROJECT", fake_pyproject)
        write_version("3.0.0")
        result = fake_pyproject.read_text()
        assert 'version = "3.0.0"' in result
        assert 'target-version = "py312"' in result
