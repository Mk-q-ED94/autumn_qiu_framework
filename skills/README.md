# Autumn Skills

Agent skills for Autumn. Each `SKILL.md` has YAML frontmatter (`name` + `description`)
and is portable across Claude Code / Codex / Cursor.

## Layout

```
skills/
├── taste-skill/SKILL.md          # CUSTOMIZED — Autumn design taste (Paper & Clay, 3 clients)
├── web-design-engineer/SKILL.md  # CUSTOMIZED — Autumn React web design engineer
├── everos-memory/SKILL.md        # CUSTOMIZED — Autumn 4D memory usage (recall/remember/annotate)
└── upstream/                     # PRISTINE upstream sources, kept for diff/reference
    ├── taste-skill/SKILL.md          # Leonxlnx/taste-skill
    ├── web-design-engineer/SKILL.md  # ConardLi/web-design-skill
    └── everos-memory/SKILL.md        # EverMind-AI/EverOS (claude-code-plugin)
```

- **Top-level dirs** are the **Autumn-authored, customized** skills — rewritten to target
  Autumn's actual stack, design language, and 4D memory engine.
- **`upstream/`** holds the **unmodified** sources they were adapted from, so the
  customization is always diffable against its origin.

## Status: not yet activated

These live in `skills/`, **not** `.claude/skills/`, so Claude Code does **not** auto-load
them. They are reviewed source. To activate one, copy (or symlink) its directory into
`.claude/skills/` after review.

## Customization summary

| Skill | Retargeted from → to |
|-------|----------------------|
| `taste-skill` | arbitrary web landing pages (max variance) → Autumn's three clients, Paper & Clay, restraint + cross-client parity |
| `web-design-engineer` | greenfield React+Tailwind+CDN → Autumn's real `web/frontend` (React 18 + Vite + plain CSS, no framework) |
| `everos-memory` | EverMem **cloud** `evermem_search` → Autumn's local **4D memory** (recall/remember/annotate/pin, Mom1/2/3/shared, access control, HTTP API) |

Related analysis: [`docs/everos-4d-memory-takeaways.md`](../docs/everos-4d-memory-takeaways.md)
— what EverOS does that's worth adopting for Autumn's 4D memory.
