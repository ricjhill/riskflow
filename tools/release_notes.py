"""Generate release notes from merged PRs since the last git tag.

Fetches merged PRs via `gh pr list`, categorises them by title keywords
(features, fixes, infrastructure, docs), and formats Markdown suitable
for GitHub releases.

Usage:
    uv run python -m tools.release_notes [--since TAG] [--version VERSION]

The tool is also importable for use by the /release skill and release.yml.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

# Category patterns — matched case-insensitively against PR title.
# Each pattern is a regex. Order matters: first match wins.
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("fixes", [r"\bfix", r"\bupgrade\b", r"\bbump\b", r"\bpatch\b", r"\bcve\b", r"\bsecurity\b"]),
    (
        "infrastructure",
        [
            r"\bci\b",
            r"\bcd\b",
            r"\bdocker\b",
            r"\bworkflow\b",
            r"\bhook\b",
            r"\bpre-commit\b",
            r"\bcoverage\b",
            r"\brelease\b",
            r"\blint",
        ],
    ),
    (
        "docs",
        [
            r"\bdocs?\b",
            r"\bdocumentation\b",
            r"\breadme\b",
            r"\bpresentation\b",
            r"\bsession\b",
            r"\blesson",
        ],
    ),
    # "features" is the fallback — anything with "add", "implement", "new",
    # or anything that doesn't match another category.
    (
        "features",
        [r"\badd\b", r"\bimplement", r"\bnew\b", r"\bcreate\b", r"\bsupport\b", r"\benable\b"],
    ),
]

_SECTION_HEADERS: dict[str, str] = {
    "features": "**Features**",
    "fixes": "**Bug fixes**",
    "infrastructure": "**Infrastructure**",
    "docs": "**Documentation**",
}

# Render order
_SECTION_ORDER = ["features", "fixes", "infrastructure", "docs"]


@dataclass
class PR:
    """A merged pull request."""

    number: int
    title: str
    merged_at: str


def categorise_pr(pr: PR) -> str:
    """Assign a PR to a category based on title keywords.

    Uses word-boundary matching to avoid false positives (e.g. "Docker"
    should not match the "doc" keyword).

    Returns one of: "features", "fixes", "infrastructure", "docs".
    """
    title_lower = pr.title.lower()
    for category, patterns in _CATEGORY_RULES:
        for pattern in patterns:
            if re.search(pattern, title_lower):
                return category
    return "features"


def group_prs(prs: list[PR]) -> dict[str, list[PR]]:
    """Group PRs by category, sorted by PR number within each group."""
    groups: dict[str, list[PR]] = {cat: [] for cat in _SECTION_ORDER}
    for pr in prs:
        cat = categorise_pr(pr)
        groups[cat].append(pr)
    for cat in groups:
        groups[cat].sort(key=lambda p: p.number)
    return groups


def format_release_notes(version: str, prs: list[PR]) -> str:
    """Format PRs into Markdown release notes.

    Returns a string suitable for `gh release create --notes`.
    """
    lines = [f"### What's new in v{version}", ""]

    if not prs:
        lines.append("No merged PRs since the last release.")
        return "\n".join(lines)

    groups = group_prs(prs)

    for section in _SECTION_ORDER:
        section_prs = groups[section]
        if not section_prs:
            continue
        lines.append(_SECTION_HEADERS[section])
        for pr in section_prs:
            lines.append(f"- {pr.title} (#{pr.number})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI — fetch PRs from GitHub and generate notes
# ---------------------------------------------------------------------------


def fetch_prs_since_tag(tag: str) -> list[PR]:
    """Fetch merged PRs since the given tag using `gh pr list`."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        "100",
        "--json",
        "number,title,mergedAt",
        "--jq",
        f'.[] | select(.mergedAt > "{_tag_date(tag)}") | "\\(.number)\\t\\(.title)\\t\\(.mergedAt)"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    prs = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) == 3:
            prs.append(PR(number=int(parts[0]), title=parts[1], merged_at=parts[2]))
    return prs


def _tag_date(tag: str) -> str:
    """Get the date of a git tag in ISO format."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%aI", tag],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_latest_tag() -> str | None:
    """Get the most recent semver tag, or None if no tags exist."""
    result = subprocess.run(
        ["git", "tag", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        if re.match(r"^v?\d+\.\d+\.\d+$", line.strip()):
            return line.strip()
    return None


def main() -> None:
    """CLI entry point: fetch PRs since last tag and print release notes."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate release notes from merged PRs")
    parser.add_argument("--since", help="Git tag to compare from (default: latest tag)")
    parser.add_argument(
        "--version", help="Version string for the header (default: from pyproject.toml)"
    )
    args = parser.parse_args()

    tag = args.since or get_latest_tag()
    if not tag:
        print("No tags found. Cannot generate release notes.", file=sys.stderr)
        sys.exit(1)

    version = args.version
    if not version:
        from tools.bump_version import read_version

        version = read_version()

    prs = fetch_prs_since_tag(tag)
    notes = format_release_notes(version, prs)
    print(notes)


if __name__ == "__main__":
    main()
