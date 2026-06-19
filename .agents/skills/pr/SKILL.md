---
name: pr
description: Open or update a pull request for the Autumn repo with a proper title and body. Use ONLY when the user explicitly asks for a PR. Runs checks first, targets the right base, and writes a Summary + Test plan — no model identifiers.
---

# /pr — Autumn pull-request workflow

> **Do not open a PR unless the user explicitly asks.** Committing/pushing ≠ opening a PR.

## Before opening
1. Ensure the branch is pushed and up to date with its base.
2. Run checks and record results for the test plan:
   ```bash
   ruff check .
   pytest
   ```
   WinUI (`windows/`) / SwiftUI (`desktop/`) can't build in Linux CI — state that
   explicitly and mark those boxes as needing a local build.

## Base & title
- **Base**: `main` (Windows-client PRs also target `main`, e.g. PR #20).
- **Title**: Conventional Commits style — `feat(scope): …`, `fix(scope): …`.

## Body template
```markdown
## Summary
- what changed and why (1–4 bullets)

## Test plan
- [x] ruff check . — clean
- [x] pytest — N passed
- [ ] (WinUI/SwiftUI) local build — cannot run in CI
```

## Rules
- **No model identifiers** in the title or body (per repo policy).
- Keep the PR scoped to one branch's logical change; don't bundle unrelated work.
- After opening, you may offer to watch the PR for CI/review activity — but only act on
  review feedback per the user's guidance.
