---
name: new-branch
description: Create a git branch for new Autumn work following the repo's branch policy and naming. Use when starting a feature/fix that should not land directly on the current branch, or when the user asks to start a new branch.
---

# /new-branch — Autumn branch workflow

## Branch policy
- **`main`** — Python framework + general work + agent skills/docs. Most work branches from here.
- **`claude/windows-client`** — **Windows client only** (tracked by PR #20). Put Windows
  WinUI/desktop work here; keep non-Windows work off it.

## Naming
Agent topic branches use an agent prefix + short kebab topic, matching existing branches
(`claude/4d-memory-rfc`, `claude/mom1-access-control`, `claude/terr-management-ui`):
```
claude/<short-topic>        # e.g. claude/markdown-memory-backend
```
`feat/<topic>` / `fix/<topic>` are also acceptable for conventional work.

## Process
1. Pick the correct base: Windows work → `claude/windows-client`; everything else → `main`.
2. Sync the base first:
   ```bash
   git checkout <base> && git pull origin <base>
   ```
3. Create and switch:
   ```bash
   git checkout -b claude/<short-topic>
   ```
4. When pushing the first time: `git push -u origin claude/<short-topic>`.

## Rules
- Don't develop large/risky changes directly on `main` — branch first.
- Don't mix Windows-client and general changes on one branch (the split is intentional).
- Don't open a PR unless the user asks (see `/pr`).
