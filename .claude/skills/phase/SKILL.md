---
name: phase
description: Phased implementation workflow — read your project's tracker, implement one phase item by item with the tests of the touched files after each, update the tracker, plan the next phase; commit and push only when the user asks. Invoke when asked to implement the next phase of a plan.
---

# /phase — Phased Implementation Workflow

A structured workflow for phased implementation. Used for infrastructure, features, and cleanups.

## Workflow

1. **Read the current state**: find and read the project's tracker files (INDEX.md, PROGRESS.md, a master tracker, or equivalent). Identify the next phase to implement.

2. **Read the phase plan**: read the detailed plan document for the current phase. Understand exactly what to implement.

3. **Implement each item**:
   - For each item in the phase, make the change
   - After each item, run the tests for the touched files (`uv run pytest tests/<file> -q`) and confirm 0 regressions.
     ⛔ Do not run the full test suite if it is memory-heavy on the current machine: run only the files you touched.
   - If a test fails, diagnose and fix it before moving on

4. **Commit, only when the user asks**: never commit on your own. When the user asks for it, use a
   conventional-commit message that references the phase/item ID
   - Format: `feat: complete phase N — item description`
   - Otherwise leave the changes in the working tree and list them in the report (step 7)

5. **Update the tracker**: update the tracker files (PROGRESS.md, INDEX.md) marking the phase done with a timestamp and test count.

6. **Plan the next phase**: write the detailed plan for the next phase in the appropriate document.

7. **Report**: never push on your own; push only when the user asks. Produce a summary:
   - What was completed
   - What is committed and what is still only in the working tree
   - Total tests (before/after)
   - What remains
   - Any blockers

## Rules
- If you hit a blocker you cannot resolve, document it in the tracker under ## Blockers and move on to the next item
- Never proceed to the next phase without the user's approval
- Every phase must close with 0 test regressions
