"""Tests for tools/release_notes.py — release note generation from merged PRs.

Verifies that merged PR data is correctly categorised into features, fixes,
infrastructure, and docs sections, and formatted into human-readable Markdown
suitable for GitHub releases.
"""

from __future__ import annotations

import pytest

from tools.release_notes import (
    PR,
    categorise_pr,
    format_release_notes,
    group_prs,
)


def _pr(title: str) -> PR:
    """Helper to build a PR with only the title varying."""
    return PR(number=1, title=title, merged_at="2026-04-12T00:00:00Z")


class TestPRCategorisation:
    """Categorise PRs into features, fixes, infrastructure, or docs by title keywords."""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            # Features
            ("Add RedisJobStore adapter", "features"),
            ("Implement schema validation", "features"),
            ("Create new endpoint for jobs", "features"),
            ("Something completely new", "features"),
            # Fixes
            ("Fix SLM confidence anchoring", "fixes"),
            ("Upgrade pygments 2.20.0", "fixes"),
            ("Bump python-multipart to 0.0.26", "fixes"),
            ("FIX broken import", "fixes"),
            # Infrastructure
            ("Move coverage delta check from pre-commit to CI", "infrastructure"),
            ("Add CI concurrency job", "infrastructure"),
            ("Add Docker multi-worker and log rotation", "infrastructure"),
            ("Release v0.3.0 — scaling", "infrastructure"),
            ("Add pre-commit hook for linting", "infrastructure"),
            # Docs
            ("Update diataxis docs for v0.3.0", "docs"),
            ("Add 12 April session presentation", "docs"),
            ("Update documentation for scaling", "docs"),
            ("Add Lessons Learned to past sessions", "docs"),
        ],
        ids=lambda x: x if isinstance(x, str) and len(x) > 10 else x,
    )
    def test_categorise_by_title(self, title: str, expected: str) -> None:
        assert categorise_pr(_pr(title)) == expected

    def test_fixture_is_not_a_fix(self) -> None:
        """'fixture' contains 'fix' as a prefix — word boundary prevents false match."""
        assert categorise_pr(_pr("Add test fixture for upload endpoint")) == "features"

    def test_docker_is_not_docs(self) -> None:
        """'Docker' contains 'doc' as a substring — word boundary prevents false match."""
        assert categorise_pr(_pr("Add Docker support")) == "infrastructure"


class TestGroupPRs:
    """Group a list of PRs by category into a dict of lists."""

    def test_groups_mixed_prs(self) -> None:
        prs = [
            PR(number=1, title="Add new endpoint", merged_at="2026-04-12T00:00:00Z"),
            PR(number=2, title="Fix validation bug", merged_at="2026-04-12T00:00:00Z"),
            PR(number=3, title="Update docs", merged_at="2026-04-12T00:00:00Z"),
            PR(number=4, title="Add CI job", merged_at="2026-04-12T00:00:00Z"),
        ]
        groups = group_prs(prs)
        assert len(groups["features"]) == 1
        assert len(groups["fixes"]) == 1
        assert len(groups["docs"]) == 1
        assert len(groups["infrastructure"]) == 1

    def test_empty_list(self) -> None:
        groups = group_prs([])
        assert groups["features"] == []
        assert groups["fixes"] == []
        assert groups["docs"] == []
        assert groups["infrastructure"] == []

    def test_all_same_category(self) -> None:
        prs = [
            PR(number=1, title="Fix bug A", merged_at="2026-04-12T00:00:00Z"),
            PR(number=2, title="Fix bug B", merged_at="2026-04-12T00:00:00Z"),
        ]
        groups = group_prs(prs)
        assert len(groups["fixes"]) == 2
        assert len(groups["features"]) == 0


class TestFormatReleaseNotes:
    """Format grouped PRs into Markdown release notes."""

    def test_basic_formatting(self) -> None:
        prs = [
            PR(number=1, title="Add new endpoint", merged_at="2026-04-12T00:00:00Z"),
            PR(number=2, title="Fix validation bug", merged_at="2026-04-12T00:00:00Z"),
        ]
        notes = format_release_notes("0.4.0", prs)
        assert "### What's new in v0.4.0" in notes
        assert "Add new endpoint (#1)" in notes
        assert "Fix validation bug (#2)" in notes

    def test_sections_only_appear_when_populated(self) -> None:
        prs = [
            PR(number=1, title="Fix a bug", merged_at="2026-04-12T00:00:00Z"),
        ]
        notes = format_release_notes("0.4.0", prs)
        assert "**Features**" not in notes
        assert "**Bug fixes**" in notes

    def test_empty_prs_produces_minimal_notes(self) -> None:
        notes = format_release_notes("0.4.0", [])
        assert "### What's new in v0.4.0" in notes
        assert "No merged PRs" in notes

    def test_all_four_sections(self) -> None:
        prs = [
            PR(number=1, title="Add feature X", merged_at="2026-04-12T00:00:00Z"),
            PR(number=2, title="Fix bug Y", merged_at="2026-04-12T00:00:00Z"),
            PR(number=3, title="Update documentation", merged_at="2026-04-12T00:00:00Z"),
            PR(number=4, title="Add CI workflow", merged_at="2026-04-12T00:00:00Z"),
        ]
        notes = format_release_notes("0.4.0", prs)
        assert "**Features**" in notes
        assert "**Bug fixes**" in notes
        assert "**Documentation**" in notes
        assert "**Infrastructure**" in notes

    def test_pr_numbers_are_linked(self) -> None:
        prs = [
            PR(number=42, title="Add cool thing", merged_at="2026-04-12T00:00:00Z"),
        ]
        notes = format_release_notes("0.4.0", prs)
        assert "(#42)" in notes

    def test_prs_sorted_by_number_within_group(self) -> None:
        prs = [
            PR(number=5, title="Add feature B", merged_at="2026-04-12T00:00:00Z"),
            PR(number=3, title="Add feature A", merged_at="2026-04-12T00:00:00Z"),
        ]
        notes = format_release_notes("0.4.0", prs)
        # #3 should appear before #5
        pos_3 = notes.index("#3")
        pos_5 = notes.index("#5")
        assert pos_3 < pos_5


class TestPRDataclass:
    """PR dataclass construction and validation."""

    def test_pr_fields(self) -> None:
        pr = PR(number=1, title="Test", merged_at="2026-04-12T00:00:00Z")
        assert pr.number == 1
        assert pr.title == "Test"
        assert pr.merged_at == "2026-04-12T00:00:00Z"
