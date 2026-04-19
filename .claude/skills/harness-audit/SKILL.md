---
name: harness-audit
description: Adversarial audit of the engineering harness — tests, CI, hooks, architecture enforcement, branch protection. Finds gaps between claims and reality.
---

Run an adversarial evaluation of the RiskFlow engineering harness. The goal is to debunk, not confirm — treat every claim as suspect until verified by evidence.

## What to audit (in order)

### 1. Branch protection
```bash
gh api repos/ricjhill/riskflow/branches/main/protection
```
- Are required status checks still configured?
- Does `enforce_admins` still block admin bypass?
- Are the right CI jobs in the required list? Compare against `.github/workflows/ci.yml` job names.
- Can force-pushes still reach main?

### 2. Test suite integrity
```bash
uv run pytest --co -q tests/ 2>&1 | tail -1    # test count
uv run pytest -x tests/unit/ 2>&1 | tail -3     # pass/fail
uv run python -m tools.coverage_report --no-run  # coverage
```
- Are all tests passing? Any new skips?
- Has coverage dropped since baseline?
- Spot-check 3 random test files: do assertions test real behavior or just that code runs?
- Check for new `pytest.raises` without `match=`: `grep -r 'pytest.raises' tests/unit/ | grep -v 'match='`
- Check for test classes without docstrings: look for `class Test` not followed by a docstring

### 3. Architecture enforcement
```bash
uv run python -m tools.hexagonal_linter
```
- Does the linter pass? If so, verify it would CATCH a violation:
  - `grep -r 'import structlog' src/domain/` — should find nothing
  - `grep -r 'import redis' src/domain/` — should find nothing
  - `grep -r 'os.environ' src/adapters/ src/domain/` — should find nothing
- Check for new infrastructure imports that bypassed the ban list

### 4. Hook enforcement
- Read `.claude/hooks/enforce-create-pr.sh` — does it still validate content length (>20 chars)?
- Read `.claude/hooks/security-scan.sh` — does it still block on pip-audit/bandit findings?
- Read `.claude/hooks/check-boundaries.sh` — does it still run the hexagonal linter?
- Test: `uv run pip-audit` — any new CVEs?

### 5. CI/CD pipeline
- Read `.github/workflows/ci.yml` — any jobs removed or weakened?
- Read `.github/workflows/cd.yml` — is Trivy image scan still present?
- Check latest CI run: `gh run list --limit 3` — are runs passing?

### 6. Security posture
```bash
uv run pip-audit
uv run bandit -r src/ -q
```
- Any new vulnerabilities?
- Any new bandit findings?

### 7. Load test thresholds
- Read `tests/load/test_locust_ci.py` — are thresholds still at regression-detection level (500ms avg, 1000ms P95)?
- Has anyone loosened them back?

### 8. Redis error observability
- Read `src/adapters/storage/job_store.py` — are Redis errors still logged (not bare `pass`)?

## Output format

```
## Harness Audit Report — <date>

### Branch Protection
- <finding or "Enforced">

### Test Suite
- <count> tests, <pass/fail>, <coverage>%
- <finding or "Healthy">

### Architecture
- Linter: <GREEN/RED>
- <finding or "No violations">

### Hooks
- <finding or "All enforcing">

### CI/CD
- <finding or "All jobs present">

### Security
- <finding or "Clean">

### Load Tests
- <finding or "Thresholds appropriate">

### Redis Observability
- <finding or "Errors logged">

### Score: <N>/10
Previous: <N>/10 | Delta: <+/-N>

### Action items
1. <what needs fixing, or "None — harness is healthy">
```

## Action

If issues are found:
1. Report findings with severity (CRITICAL / HIGH / MEDIUM / LOW)
2. For CRITICAL/HIGH: create a fix branch and PR immediately
3. For MEDIUM/LOW: create a GitHub issue for later

If everything passes: report "Harness healthy" and the score.
