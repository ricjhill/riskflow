# Harness Audit, Release Skill & Branch Protection

**RiskFlow Engineering Session — 19 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Did | 5 min |
| 2 | The /release Skill | 5 min |
| 3 | Adversarial Harness Audit | 10 min |
| 4 | Branch Protection | 3 min |
| 5 | The 5 Harness Fixes | 5 min |
| 6 | The Harness-Auditor Agent | 5 min |
| 7 | By the Numbers | 2 min |
| 8 | Lessons Learned | 5 min |
| 9 | What's Next | 2 min |

---

## 1. What We Did (5 min)

8 PRs merged, 3 new issues created, 1 new agent, 1 new skill, branch protection enabled. The session focused on release automation and hardening the engineering harness after an adversarial audit exposed gaps.

| PR | Title |
|----|-------|
| #175 | Add /release skill and release notes generator |
| #176 | Log Redis errors explicitly instead of silent swallow |
| #177 | Add infrastructure import detection to hexagonal linter |
| #178 | Add content-length validation to PR template hook |
| #179 | Add Trivy container image scanning to CD pipeline |
| #180 | Tighten Locust load test thresholds from 5000ms to 500ms |
| #181 | Add /harness-audit skill |
| #182 | Extract harness-auditor agent, slim skill to thin wrapper |

---

## 2. The /release Skill (5 min)

### The problem

Version bumps were manual and error-prone. v0.3.0 was missed through 20 PRs because the automated `release.yml` only detects OpenAPI spec changes — it missed the release because the spec was regenerated in a feature PR. Non-API changes (bug fixes, docs, infrastructure) never trigger a release.

### The solution

A new `/release` skill backed by `tools/release_notes.py`:

1. **Detect changes** — compare OpenAPI spec + list merged PRs since last tag
2. **Classify version bump** — breaking (major), non-breaking (minor), non-API (patch)
3. **Generate release notes** — categorise PRs into features, fixes, infrastructure, docs using word-boundary regex matching
4. **Execute release** — bump version, regenerate spec, commit, tag, push, create GitHub release

### Key design decision: word-boundary regex

Initial implementation used substring matching — "Docker" matched the docs category because the keyword `"doc"` is a substring of `"docker"`. Switched to word-boundary regex patterns (`\bdocs?\b` / `\bdocker\b`). The code reviewer then caught that `\bfix` (no closing boundary) would match "fixture" — fixed to explicit `\bfix\b`, `\bfixes\b`, `\bfixed\b`.

### Also added

- `bump_patch()` to `tools/bump_version.py` — patch bumps weren't supported
- Fixed CVE-2026-40347 (python-multipart 0.0.22 → 0.0.26) caught by security hook during development

---

## 3. Adversarial Harness Audit (10 min)

### What is it

An adversarial evaluation where every harness claim is treated as suspect until verified by evidence. The goal is to debunk, not confirm.

### Initial score: 5.4/10

| Area | Score | Key finding |
|------|-------|-------------|
| Test suite quality | 8 | Genuinely strong — 989 tests, real behavioral assertions |
| Hexagonal enforcement | 4 | **Misleading** — linter said GREEN but structlog was in domain |
| Pre-commit hooks | 7 | Genuine blocking — mypy, pytest, ruff, boundaries, security |
| PR template enforcement | 2 | **Theater** — checked headers existed, not content |
| 5-user scaling proof | 5 | **Misleading** — framework proven, real throughput not |
| Graceful degradation | 3 | **Misleading** — silent data loss, not graceful |
| CI/CD pipeline | 7 | Comprehensive CI, but CD had no image scanning |
| Security scanning | 7 | pip-audit and bandit genuine, semgrep optional |
| Branch protection | 0 | **Main was unprotected** — anyone could merge a red PR |

### What "misleading" means

The linter reported GREEN. But `src/domain/service/mapping_service.py` imported structlog directly — violating CLAUDE.md's rule that loggers must be injected. The linter only checked imports between src/ layers and treated all third-party imports as allowed. GREEN doesn't mean clean — it means the linter's rules all passed.

The same pattern repeated across multiple areas: tools reported success, but reading the actual code revealed the tools weren't checking what we assumed they were checking.

---

## 4. Branch Protection (3 min)

### Before: nothing

Main was completely unprotected. No required status checks, no admin enforcement, no force-push protection. Every CI check and hook was advisory — you could merge a red PR or push directly to main.

### After: fully enforced

```bash
gh api repos/ricjhill/riskflow/branches/main/protection --method PUT
```

| Rule | Setting |
|------|---------|
| Required checks | quality, security, boot-test, concurrency-test |
| Branch must be up-to-date | Yes (strict) |
| Enforce for admins | Yes |
| Force pushes | Blocked |
| Branch deletion | Blocked |

Also enabled auto-merge so PRs merge automatically once CI passes and the branch is up-to-date.

---

## 5. The 5 Harness Fixes (5 min)

Each fix addressed a specific adversarial audit finding. All developed in parallel using isolated worktree agents.

### Fix 1: Redis error logging (#176)

**Before:** `except (ConnectionError, RedisError): pass` — silent data loss.
**After:** `self._logger.error("job_store_save_failed", job_id=job.id, error=str(exc))` — errors observable.

### Fix 2: Hexagonal linter infrastructure detection (#177)

**Before:** Linter allowed all third-party imports in domain.
**After:** Ban list (`structlog`, `redis`, `httpx`, `fastapi`, `uvicorn`, `groq`) enforced in domain/ports. MappingService now receives logger via constructor injection.

### Fix 3: PR template content validation (#178)

**Before:** Hook checked `## Summary` header existed — empty sections passed.
**After:** Python parser extracts section content, rejects sections with <20 characters after stripping whitespace and markdown decoration.

### Fix 4: Trivy image scanning (#179)

**Before:** Docker images pushed to GHCR without vulnerability scan.
**After:** `aquasecurity/trivy-action@v0.28.0` scans between build and push. Blocks on CRITICAL/HIGH. Ignores unfixed.

### Fix 5: Locust threshold tightening (#180)

**Before:** 5000ms average response threshold — 100x too generous for mocked SLM (20-50ms responses).
**After:** 500ms average, 1000ms P95. Still generous but catches real regressions, not just crashes.

---

## 6. The Harness-Auditor Agent (5 min)

### Why an agent, not just a skill

The audit logic needed to be reusable — invokable from the `/harness-audit` skill, schedulable weekly, and runnable in the background. An agent can be spawned independently; a skill can only be invoked interactively.

### Pattern: agent as source of truth, skill as thin wrapper

```
.claude/agents/harness-auditor.md   ← logic (single source of truth)
.claude/skills/harness-audit/SKILL.md  ← thin wrapper that invokes the agent
```

Same pattern as:
```
.claude/agents/code-reviewer.md     ← logic
.claude/skills/create-pr/SKILL.md   ← wrapper that invokes it
```

### Adversarial methodology embedded inline

Each of the 8 checks has an **Attack** step that forces the agent to look beyond tool output:

| Check | Attack question |
|-------|----------------|
| Branch protection | Could a PR rename a CI job to bypass required checks? |
| Test suite | Pick 2 random test files — do assertions test real behavior? |
| Architecture | What about runtime coupling via `Any` type annotations? |
| Hooks | Hooks gate Claude Code — what about GitHub web UI? |
| CI/CD | Any `continue-on-error: true` silently swallowing failures? |
| Security | pip-audit checks declared deps — what about transitive deps? |
| Load tests | Do tests accept 503 as success? |
| Observability | Errors logged but no health check — do errors pile up unread? |

### First run found new issues

The agent discovered that silent error swallowing affects ALL 5 Redis adapters (not just job_store), that the `/health` endpoint doesn't probe Redis, and that `test_failed_task_updates_job_to_failed` has an overly permissive assertion.

---

## 7. By the Numbers (2 min)

| Metric | Start of session | End of session |
|--------|-----------------|---------------|
| PRs merged (total) | ~173 | 182 |
| Tests | ~989 | 994+ |
| Coverage | 96.5% | 96.5% |
| Open issues | 4 (#136, #164, #169, #174) | 4 (#183, #184, #185 + existing) |
| Skills | 2 (cleanup, create-pr) | 4 (+release, harness-audit) |
| Agents | 2 (code-reviewer, doc-gardener) | 3 (+harness-auditor) |
| Branch protection | None | Fully enforced |
| Harness score | 5.4/10 (initial) → 5.9/10 (after protection) | 6.6/10 (post-audit, pre-fix-merge) |
| CVEs fixed | 0 | 1 (CVE-2026-40347) |

### Session output: 8 PRs in 1 day

- 1 release skill PR (tools/release_notes.py + bump_patch)
- 5 harness fix PRs (Redis logging, linter, template hook, Trivy, Locust)
- 2 harness agent/skill PRs
- 3 new issues from audit findings

---

## 8. Lessons Learned (5 min)

### What went wrong

| Problem | Impact | Fix applied |
|---------|--------|-------------|
| **Main branch was unprotected** | Any PR could merge regardless of CI status. Direct pushes to main allowed. Every harness check was advisory only. | Added branch protection with 4 required checks, admin enforcement, strict updates |
| **Harness tools reported GREEN while hiding real gaps** | Hexagonal linter said GREEN with structlog in domain. PR template hook "validated" empty sections. RedisJobStore "degraded gracefully" by silently losing data. | Each tool was fixed to check what it claimed to check |
| **Audit was one-off, not repeatable** | The adversarial evaluation found 5 real issues, but there was no mechanism to detect future drift | Created harness-auditor agent with inline attack steps, schedulable weekly |
| **Sub-agents gave incorrect claims during audit** | One agent claimed PR template hook was "FIXED" and RedisJobStore was "FIXED" — both were wrong. The template hook still only checked headers. The debug log didn't log the error. | Verified every sub-agent claim by reading the actual code. Tool output is untrusted evidence — including from other agents. |
| **Word-boundary regex had subtle false positives** | Initial `\bfix` matched "fixture", `"doc"` matched "Docker". Code reviewer caught `\bfix` → "fixture" but the Docker issue was found during development. | Switched to explicit whole-word patterns with tests for each false positive case |

### What should change

1. **Never trust tool output without reading the code** — "linter says GREEN" and "agent says FIXED" are both claims, not proof. The adversarial methodology (run tool → attack result → verify by reading code) should be the default for all audit work.
2. **Branch protection should have been Day 1** — it was the single biggest gap and the simplest fix. Every harness check was advisory without it.
3. **Fix PRs should cover the full scope** — PR #176 fixed job_store.py but the same silent-swallow pattern existed in 4 other Redis adapters. The audit found what the fix missed.
4. **Agent claims need verification** — sub-agents confidently reported things as "FIXED" that weren't. The skill/agent pattern (agent does the work, skill relays results) needs the relay step to include spot-checking, not just forwarding.

### What went well

- The adversarial evaluation found 5 real issues that the existing harness missed — every fix was justified by evidence, not speculation
- All 5 fixes were developed in parallel using isolated worktree agents — total wall-clock time was ~10 minutes for all 5
- The harness-auditor agent's first real run found 3 new issues (#183, #184, #185) beyond what the manual audit caught
- Branch protection + auto-merge creates a reliable merge queue — PRs can't land without green CI, and they merge automatically when ready
- The /release skill fills a real gap — v0.3.0 was missed because the automated workflow couldn't detect non-API changes

---

## 9. What's Next (2 min)

| # | Title | Type |
|---|-------|------|
| #183 | Add error logging to all 5 Redis adapters | Observability |
| #184 | Add Redis connectivity probe to /health endpoint | Observability |
| #185 | Fix overly permissive test assertion | Testing |
| #174 | Update scaling roadmap — Phase 4 for 50 users | Planning |
| #169 | Create /release skill (DONE — PR #175) | Harness |
| #136 | Confidence endpoint for human-provided mappings | Feature |
| #164 | Concurrent e2e test with real Groq API | Testing |

The harness is now self-auditing. The next priority is closing the observability gaps (#183, #184) found by the first auditor run, then resuming feature work.
