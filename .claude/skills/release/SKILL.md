---
name: release
description: Bump version, generate release notes from merged PRs, tag, push, and create a GitHub release. Handles both API-change and non-API-change releases.
---

Create a new release for RiskFlow. This skill handles the full release workflow — from detecting what changed to publishing a GitHub release with categorised release notes.

## When to use

- After merging a batch of PRs that include non-API changes (bug fixes, docs, infrastructure) that the automated `release.yml` won't detect
- When you want richer release notes than the automated workflow generates
- When the automated workflow skipped a release and you need to catch up
- When the user explicitly asks for `/release`

## Steps

### Phase 1: Assess what changed

1. Get the latest release tag:
   ```bash
   git tag --sort=-v:refname | head -1
   ```

2. Get the current version:
   ```bash
   grep '^version' pyproject.toml
   ```

3. List commits since the last tag:
   ```bash
   git log --oneline <last-tag>..HEAD
   ```

4. Check for API changes by comparing the OpenAPI spec:
   ```bash
   uv run python -c "
   import json
   from tools.check_api_changes import detect_changes
   from tools.export_openapi import main as export_spec
   import tempfile, pathlib
   # Get spec from last tag
   import subprocess
   tag = subprocess.run(['git', 'tag', '--sort=-v:refname'], capture_output=True, text=True).stdout.strip().split('\n')[0]
   old_spec = json.loads(subprocess.run(['git', 'show', f'{tag}:openapi.json'], capture_output=True, text=True).stdout)
   # Get current spec
   tmp = tempfile.mktemp(suffix='.json')
   export_spec(tmp)
   new_spec = json.loads(pathlib.Path(tmp).read_text())
   result = detect_changes(old_spec, new_spec)
   print(result)
   "
   ```

5. Fetch merged PRs since the last tag:
   ```bash
   uv run python -m tools.release_notes --since <last-tag>
   ```

### Phase 2: Determine version bump

Based on Phase 1 findings, classify the release:

| Condition | Bump | Example |
|-----------|------|---------|
| API breaking changes detected | Major | 0.3.0 → 1.0.0 |
| API non-breaking changes detected | Minor | 0.3.0 → 0.4.0 |
| Non-API changes only (bug fixes, docs, infra) | Patch | 0.3.0 → 0.3.1 |
| No changes since last tag | Skip | No release |

**Important:** The automated `release.yml` only bumps major/minor for API changes. This skill adds **patch** bumps for non-API changes — that's the gap it fills.

Present the proposed version to the user and get confirmation before proceeding.

### Phase 3: Generate release notes

Use the release notes tool to generate categorised notes:

```bash
uv run python -m tools.release_notes --since <last-tag> --version <new-version>
```

Review the output. The tool categorises PRs into:
- **Features** — new functionality
- **Bug fixes** — fixes, upgrades, security patches
- **Infrastructure** — CI, Docker, hooks, coverage, linting
- **Documentation** — docs, presentations, lessons learned

Edit the notes if needed (add context, highlight important changes, add test/coverage stats).

### Phase 4: Execute release

1. Update the version in `pyproject.toml`:
   ```bash
   uv run python -c "from tools.bump_version import write_version; write_version('<new-version>')"
   ```

2. Regenerate the OpenAPI spec with the new version:
   ```bash
   uv run python -m tools.export_openapi
   ```

3. Run all checks to make sure nothing is broken:
   ```bash
   uv run pytest -x tests/unit/
   uv run mypy src/
   uv run ruff check src/
   uv run ruff format --check src/
   ```

4. Commit the version bump:
   ```bash
   git add pyproject.toml openapi.json
   git commit -m "Release v<new-version> — <one-line summary>"
   ```

5. Tag and push:
   ```bash
   git tag v<new-version>
   git push origin main --tags
   ```

6. Create the GitHub release:
   ```bash
   gh release create v<new-version> \
     --title "v<new-version> — <short summary>" \
     --notes "<release-notes>" \
     --target main \
     openapi.json
   ```

## Rules

- **Always confirm the version bump with the user** before executing Phase 4
- **Never skip the check step** — tests, mypy, and ruff must all pass before tagging
- **Include `openapi.json` as a release asset** — consumers pin to specific versions
- **Release notes must be generated from actual PR data**, not written from memory
- The release commit must be on `main` — do not release from feature branches
- If there are uncommitted changes on main, warn the user and do not proceed
- If there are no changes since the last tag, report "Nothing to release" and stop

## Relationship to release.yml

The automated `release.yml` workflow runs after CI passes on main and handles API-change releases automatically. This skill complements it by:

1. Adding **patch releases** for non-API changes (which release.yml ignores)
2. Generating **richer release notes** from PR titles (release.yml only reports OpenAPI diffs)
3. Providing a **manual trigger** when the automated workflow misses a release

Both can coexist — if you use this skill to create a release, release.yml will see NONE on its next run and skip (no conflict).
