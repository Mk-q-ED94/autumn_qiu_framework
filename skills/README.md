# Autumn Skills

Agent skills for developing Autumn. Each `SKILL.md` has YAML frontmatter
(`name` + `description`) and follows the portable Agent Skills spec
(Claude Code / Codex / Cursor).

## Where the skills live

The **active, customized** skills are mounted under `.claude/skills/` so Claude Code
auto-discovers and invokes them on demand. Codex reaches them via the root `AGENTS.md`.

```
.claude/skills/                       # ACTIVE — auto-loaded by Claude Code
├── autumn-design-taste/SKILL.md          # Paper & Clay taste across all 3 clients
├── autumn-web-design-engineer/SKILL.md   # React web (web/frontend) design engineer
└── autumn-memory/SKILL.md                # Autumn 4D memory usage

skills/upstream/                      # PRISTINE upstream sources (diff/reference only)
├── taste-skill/SKILL.md                  # Leonxlnx/taste-skill
├── web-design-engineer/SKILL.md          # ConardLi/web-design-skill
└── everos-memory/SKILL.md                # EverMind-AI/EverOS (claude-code-plugin)
```

- **`.claude/skills/`** holds the Autumn-authored, customized skills. This is the mount
  point — Claude Code loads them automatically; `CLAUDE.md` and `AGENTS.md` make them
  authoritative for both agents.
- **`skills/upstream/`** keeps the unmodified sources they were adapted from, so the
  customization is always diffable against its origin.

## Customization summary

| Active skill | Retargeted from → to |
|--------------|----------------------|
| `autumn-design-taste` | arbitrary web landing pages (max variance) → Autumn's three clients, Paper & Clay, restraint + cross-client parity |
| `autumn-web-design-engineer` | greenfield React+Tailwind+CDN → Autumn's real `web/frontend` (React 18 + Vite + plain CSS, no framework) |
| `autumn-memory` | EverMem **cloud** `evermem_search` → Autumn's local **4D memory** (recall/remember/annotate/pin, Mom1/2/3/shared, access control, HTTP API) |

Related analysis: [`docs/everos-4d-memory-takeaways.md`](../docs/everos-4d-memory-takeaways.md)
— what EverOS does that's worth adopting for Autumn's 4D memory.
