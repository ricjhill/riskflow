"""Semantic version bumping based on OpenAPI change detection.

Compares the committed openapi.json against the live app spec, classifies
the changes, and bumps the version in pyproject.toml accordingly:

- BREAKING  → major bump (e.g. 1.2.3 → 2.0.0)
- NON_BREAKING → minor bump (e.g. 1.2.3 → 1.3.0)
- NONE → no change

Usage:
    uv run python -m tools.bump_version [--dry-run]

Exits with code:
    0 — version bumped (or unchanged)
    1 — error
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from tools.check_api_changes import ChangeKind, detect_changes

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
OPENAPI_JSON = ROOT / "openapi.json"


def bump_major(version: str) -> str:
    """Bump major version, reset minor and patch to 0."""
    major, _, _ = version.split(".")
    return f"{int(major) + 1}.0.0"


def bump_minor(version: str) -> str:
    """Bump minor version, reset patch to 0."""
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def bump_patch(version: str) -> str:
    """Bump patch version, preserve major and minor."""
    major, minor, patch = version.split(".")
    return f"{major}.{minor}.{int(patch) + 1}"


def compute_next_version(current: str, change_kind: ChangeKind) -> str:
    """Compute the next version based on the kind of API change."""
    if change_kind == ChangeKind.BREAKING:
        return bump_major(current)
    if change_kind == ChangeKind.NON_BREAKING:
        return bump_minor(current)
    return current


def read_version() -> str:
    """Read the current version from pyproject.toml."""
    for line in PYPROJECT.read_text().splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    msg = "Could not find version in pyproject.toml"
    raise ValueError(msg)


def write_version(new_version: str) -> None:
    """Write the new version to pyproject.toml."""
    content = PYPROJECT.read_text()
    updated = re.sub(
        r'^version = ".*"',
        f'version = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    PYPROJECT.write_text(updated)


def main(dry_run: bool = False) -> str | None:
    """Detect API changes and bump version if needed.

    Returns the new version string if bumped, None if unchanged.
    """
    import os

    os.environ.pop("REDIS_URL", None)

    from tools.export_openapi import main as export_spec

    # Load committed spec
    if not OPENAPI_JSON.exists():
        print("No openapi.json found — skipping version bump")
        return None

    committed = json.loads(OPENAPI_JSON.read_text())

    # Generate live spec to a temp file
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    export_spec(tmp_path)
    live = json.loads(Path(tmp_path).read_text())
    Path(tmp_path).unlink()

    # Compare
    result = detect_changes(committed, live)
    current_version = read_version()
    next_version = compute_next_version(current_version, result.kind)

    print(str(result))
    print(f"Current version: {current_version}")

    if next_version == current_version:
        print("No version bump needed.")
        return None

    print(f"Next version: {next_version}")

    if not dry_run:
        write_version(next_version)
        print(f"Updated pyproject.toml to {next_version}")
        # Re-export spec with new version
        export_spec(str(OPENAPI_JSON))
        print(f"Re-exported openapi.json with version {next_version}")

    return next_version


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = main(dry_run=dry)
    if result:
        print(f"New version: {result}")
