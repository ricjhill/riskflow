---
name: harness-audit
description: Adversarial audit of the engineering harness — tests, CI, hooks, architecture enforcement, branch protection. Finds gaps between claims and reality.
---

Run an adversarial evaluation of the RiskFlow engineering harness by launching the `harness-auditor` agent.

## Steps

1. Launch the `harness-auditor` agent with this prompt:

   > Run a full harness audit. Previous overall score was 5.9/10. Check all 8 areas and report whether the score has improved or regressed.

2. When the agent returns, relay the report to the user.

3. If the agent reports CRITICAL or HIGH findings:
   - Create a fix branch for each finding
   - Implement the fix
   - Use `/create-pr` to open a PR

4. If the agent reports MEDIUM or LOW findings:
   - Create GitHub issues for later

5. If the harness is healthy: report "Harness healthy" and the score.

## Notes

- The audit logic lives in `.claude/agents/harness-auditor.md` — edit the agent to change what's checked.
- This skill is a thin wrapper that invokes the agent and handles the results.
- Can be scheduled weekly via CronCreate: `CronCreate(cron: "23 9 * * 1", prompt: "/harness-audit")`
