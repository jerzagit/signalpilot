# Feature workflow

Use this workflow for a new feature or substantial fix. Keep small fixes small;
do not require a long plan or extra approvals for routine authorized work.

1. **Describe the outcome.** Create `docs/features/<short-name>.md` using the
   [template](features/_template.md). Capture the user's goal, observable
   acceptance criteria, scope, and unresolved questions. Ask only for missing
   information that materially affects implementation.
2. **Locate the change.** Check `git status --short`, use the architecture map,
   and inspect affected code and tests. Read decisions/runbook only as relevant.
   Record important dependencies and any mismatch between docs and code.
3. **Plan proportionally.** List implementation steps and verification needed.
   Include migration/rollback only when persistence or operational behavior changes.
   Do not expand the task to unrelated cleanup.
4. **Implement.** Preserve unrelated work. Keep external services mocked and
   runtime state isolated during tests. Update progress/next step when work will
   span sessions; avoid a transcript of every tool call.
5. **Verify and review.** Check acceptance criteria, run meaningful targeted
   tests, review the diff, and inspect UI behavior for UI changes. Before any
   service restart, follow the runbook. Record actual results and limitations.
6. **Maintain knowledge.** Update architecture when boundaries/data flow change,
   the runbook when commands or operations change, and decisions when a lasting
   convention changes. Mark the feature complete only when its criteria are met.

## Definition of done

- Requested behavior is implemented and acceptance criteria checked.
- Relevant verification has evidence; failures/skips are explained.
- No unrelated local work was overwritten and no duplicate service was launched.
- Documentation affected by the change is current.
- Final handoff states what changed, what was checked, and any remaining limits.

If unfinished, use `in progress` or `blocked`, record the exact next action and
blocker, and leave enough context to resume without a full repository review.
Do not record transient PIDs or balances as permanent project facts.

## Requesting the next feature

Example:

> Add a symbol filter to Trades. Follow the repository feature workflow.
> It should combine with the existing date range and survive page refresh.

An agent should turn this into criteria, read dashboard/grouping code, implement
and verify the behavior, then update the feature record. The user should not
need to repeat the repository layout or process-management rules.
