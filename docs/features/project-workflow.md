# Persistent project knowledge and feature workflow

Status: complete
Updated: 2026-09-25

## Goal and scope

Give future agents enough persistent context to add features without repeating
a full project investigation. Preserve existing application behavior and running
services. The user explicitly requested structured workflow and no duplicate
processes.

## Acceptance criteria

- [x] Root AGENTS.md routes agents to relevant guidance and project rules.
- [x] Architecture documents inspected modules, data flow, and reporting semantics.
- [x] Runbook explains startup, singleton guards, process pairs, and safe checks.
- [x] Feature workflow includes acceptance criteria, verification, and doc updates.
- [x] Reusable feature template and initial record exist.
- [x] Links, referenced paths, and documented bounded checks verified.

## Implementation

Added root guidance, architecture, runbook, workflow, decision record, and a
feature template. Kept application code and runtime configuration unchanged.
Recorded existing full-suite isolation gaps and historical trading-guide drift
as follow-up issues, not as resolved defects.

## Verification evidence

Verified on 2026-09-25:

- Checked eight Markdown documents (including the existing trading guide); all
  six relative Markdown links resolve. Referenced module/test paths were checked
  during the architecture review.
- Ran the runbook's bounded pytest command: 30 passed.
- Ran `python -m pip check` in `.venv`: no broken requirements.
- Ran `git diff --check`: no whitespace errors; Git emitted existing CRLF warnings.
- Inspected service process command lines and parent relationships: the same one
  bot and one dashboard instance remained, each with a virtual-environment launcher.
- Full-suite and live trading verification intentionally not performed; existing
  isolation gaps are documented in the runbook.

## Operational impact

None. Documentation-only change; no bot/dashboard restart required.

## Handoff

Complete. Future features use `_template.md` and update the relevant guidance
when behavior changes. Existing trading-guide drift and test isolation gaps
remain follow-up work; this task did not alter application code or runtime data.
