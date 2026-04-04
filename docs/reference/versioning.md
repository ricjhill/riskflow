# API Versioning and Releases

RiskFlow uses semantic versioning for its API. Version bumps are automated based on what changed in the OpenAPI spec between releases.

## Version scheme

The API version follows [Semantic Versioning 2.0](https://semver.org/):

| Change type | Version bump | Example |
|-------------|-------------|---------|
| **Breaking** — removed endpoint, removed method, removed/changed required parameter, removed response status code | Major | 1.2.0 -> 2.0.0 |
| **Non-breaking** — added endpoint, added method, added optional parameter, added response status code | Minor | 1.2.0 -> 1.3.0 |
| **No API change** — internal refactoring, bug fixes, documentation | None | 1.2.0 -> 1.2.0 |

## Where the version appears

- `pyproject.toml` — the canonical source (`version = "X.Y.Z"`)
- `openapi.json` — the `info.version` field, read from `pyproject.toml` at export time
- `GET /openapi.json` — the live spec served by FastAPI
- GitHub release tags — `vX.Y.Z`

## How releases work

The release workflow (`.github/workflows/release.yml`) runs automatically after CI passes on `main`:

1. Fetches the `openapi.json` from the last release tag
2. Compares it against the current committed `openapi.json` using `tools/check_api_changes.py`
3. Classifies changes as BREAKING, NON_BREAKING, or NONE
4. If changes detected: bumps version in `pyproject.toml`, re-exports `openapi.json`, commits, and creates a GitHub release
5. If no changes: does nothing

The release includes `openapi.json` as a downloadable asset — consumers can pin to a specific version.

## Breaking change detection

The change detector (`tools/check_api_changes.py`) checks:

**Breaking (major bump):**
- Removed path (e.g. `/users` endpoint deleted)
- Removed HTTP method from a path (e.g. `DELETE /schemas/{name}` removed)
- Removed required parameter
- Required parameter made optional (or vice versa)
- Removed response status code

**Non-breaking (minor bump):**
- Added path
- Added HTTP method to existing path
- Added optional parameter
- Removed optional parameter
- Added response status code

**Not yet detected** (manual review needed):
- Changes to request/response body schemas (added/removed properties)
- Changes to parameter types (e.g. string to integer)
- Changes to response body structure within existing status codes

## Manual version bump

To bump the version manually:

```bash
# Check what changed (dry run)
uv run python -m tools.bump_version --dry-run

# Or edit pyproject.toml directly, then re-export
uv run python -m tools.export_openapi
```

## Checking for breaking changes locally

```bash
# Compare current spec against what's committed
uv run python -c "
import json
from tools.check_api_changes import detect_changes
old = json.load(open('openapi.json'))
# ... make your changes, then:
# uv run python -m tools.export_openapi /tmp/new.json
# new = json.load(open('/tmp/new.json'))
# print(detect_changes(old, new))
"
```
