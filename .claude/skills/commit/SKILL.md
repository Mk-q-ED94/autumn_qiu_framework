---
name: commit
description: Create a well-formed git commit for the Autumn repo using Conventional Commits. Use when the user asks to commit, save, or check in changes. Stages focused changes, runs lint/tests for code changes, and writes an imperative, scoped message — no model identifiers, never bypassing hooks.
---

# /commit — Autumn commit workflow

## Process
1. `git status` + `git diff` (and `git diff --staged`) — see exactly what changed.
2. `git log --oneline -10` — match the repo's existing message style.
3. **Before committing code**: `ruff check .` and `pytest` (the suite is fast). For
   WinUI (`windows/`) / SwiftUI (`desktop/`) changes, note they can't compile in CI —
   they're hand-reviewed; the user builds locally.
4. Stage **only** the files for this one logical change (`git add <paths>`, not `-A` blindly).
5. Commit with the format below.

## Message format (Conventional Commits)
```
<type>(<scope>): <imperative summary ≤ 72 chars>

<optional body: what & why, wrapped ~72>

<optional footer: BREAKING CHANGE: … / Refs: #NN>
```

**Types**: `feat` `fix` `refactor` `test` `docs` `style` `perf` `chore` `build` `ci` `revert`.
**Scopes seen in this repo**: `windows`, `desktop`, `server`, `memory`, `web`, or a module name.

## Rules
- Imperative mood ("add", not "added"). Type first, no emoji.
- One logical change per commit — keep history bisectable.
- **Never** `--no-verify`; never bypass pre-commit hooks.
- Never commit secrets, API keys, build artifacts, or `node_modules`.
- **No model identifiers** anywhere in the message (per repo policy).
- Branch first if the change doesn't belong on the current branch (see `/new-branch`):
  general work → `main`; Windows-client work → `claude/windows-client`.
