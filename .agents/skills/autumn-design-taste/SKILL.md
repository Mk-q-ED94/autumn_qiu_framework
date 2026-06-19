---
name: autumn-design-taste
description: Autumn's design-taste guardian across all three clients — WinUI 3 desktop, macOS SwiftUI desktop, and the React web app. Reads the surface, enforces the "Paper & Clay" language (one clay accent, hairline borders, hand-drawn shell, no stock platform chrome), keeps the three clients reading as one product, and runs a pre-flight check before shipping any UI. Use when building or restyling any Autumn screen, component, or visual. Not for backend, CLI, or non-visual work.
---

# Autumn Design Taste — Paper & Clay

> Adapted for Autumn from `skills/upstream/taste-skill`. The upstream skill targets
> arbitrary web landing pages and *maximises* variance. Autumn is the opposite: **one
> focused product across three clients**, where the goal is restraint and cross-platform
> coherence, not novelty. Every rule below is rewritten for that goal.

You are the taste layer for Autumn's UI. Autumn ships three native-feeling clients that
must read as **one product**:

| Client | Stack | Tokens (source of truth) |
|--------|-------|--------------------------|
| macOS desktop | SwiftUI | `desktop/AutumnApp/DesignSystem/Tokens.swift` |
| Windows desktop | WinUI 3 / .NET 8 | `windows/AutumnDesktop/App.xaml` + `DesignSystem/Tokens.cs` |
| Web | React 18 + Vite + plain CSS | `web/frontend/src/styles.css` (`:root`) |

**Tokens.swift is the canonical design language.** WinUI and CSS mirror it. When they
disagree, Tokens.swift wins and the others are the bug.

---

## 0. Read the surface before touching anything

Before writing a line, state a one-line **Design Read**:

> *Design Read: {client} · {screen} · {light/dark} · {what the user actually needs}*

Then check:
1. **Which client?** SwiftUI / WinUI / React — the idioms differ, the language does not.
2. **Which surface?** chat, memory, settings, sidebar, composer, a trace/pipeline view.
3. **Light or dark?** every token has both; never hard-code one.
4. **Is there an existing component?** Reuse `AutumnNavItem` / `AutumnTabPill` / `AutumnBadge` /
   `PipelineStripView` etc. before inventing. Parity across clients beats local cleverness.

---

## 1. The canonical language: "Paper & Clay"

A calm, neutral canvas (the way ChatGPT and Codex keep surfaces quiet) warmed by **a
single restrained clay/terracotta accent** (the way Codex carries identity through one
warm tone, not a rainbow). Hairline borders do the structural work; shadows are almost
invisible. Typography is clean system sans, never rounded.

### 1.A The one accent

`clay` is the entire brand identity. There is **exactly one accent**.

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `clay` | `#CC6645` | `#D67A55` (lifted) | primary accent — buttons, selection, focus |
| `claydeep` | `#9C452E` | — | gradient anchor, logo |
| accent text | `#9C452E` | `#E8A07E` (`ClayLight`) | accent-coloured text on each surface |

Everything else is a **desaturated companion** used ONLY for semantic status or the four
workspace identities — never as decoration:

| Token | Hex | Used for |
|-------|-----|----------|
| `sand` | `#C29E73` | soft warm neutral |
| `sage` | `#708F73` | terrs / muted green |
| `slate` | `#527A85` | info / WP3 |
| `memory` | `#82699E` | **4D memory / WP4 — the only purple in the app** |
| `success` | `#5C996B` | success status |
| `warning` | `#D69442` | warning / WP2 (amber, distinct from clay) |
| `danger` | `#CC544D` | errors |

### 1.B The four workspace identities

Colour is meaning, not decoration. The pipeline/trace views encode workspace identity:

| Workspace | Desktop colour | Meaning |
|-----------|---------------|---------|
| WP1 / A1 | `clay` | orchestration (selector / checker) |
| WP2 / A2 | `warning` amber | task execution |
| WP3 / A3 | `slate` | mission |
| WP4 / A4 | `memory` purple | 4D memory engine |

> ⚠️ The **web client diverges** (see §3). Desktop is canonical.

### 1.C Surfaces, borders, radius

- **Surfaces** are built from translucency over a material/Mica canvas, not opaque fills:
  `surfaceElevated ≈ primary @ 4%`, hover `@ 7%`, active `@ 10.5%`. Warm paper sidebar
  (`#F3EDE7` light / `#1C1814` dark) is the one named solid.
- **Borders** are hairline (0.5pt macOS / 1px elsewhere) and do the structural work.
- **Shadows** are near-invisible (`subtle` = black @ 4%). Lean on borders, not elevation.
- **Radius** ladder: `xs 4 · sm 7 · md 11 · lg 16 · xl 22 · pill 999` (macOS/WinUI).
  Web uses `xs4 · sm6 · md10 · lg16 · full9999`.
- **Chat bubbles**: user turns carry a hint of clay (`clay @ 12%` fill, `@ 30%` stroke);
  assistant turns stay neutral and near-borderless (`primary @ 3.5%`).

---

## 2. Anti-slop rules (Autumn edition)

These exist because they were real regressions in this codebase. None fire automatically —
apply by judgement.

**Hard bans:**
- ❌ **Stock platform chrome.** No bare WinUI `NavigationView`, no default `TextBox`
  underline focus, no stock `SelectorBar`, no `InfoBar`. Autumn draws its own shell:
  custom title bar, `AutumnNavItem` sidebar, `AutumnTabPill` tabs, inline danger strips.
  (This was the whole "标准毛坯 → 自有外壳" refactor — do not regress it.)
- ❌ **Rainbow UI.** One accent (clay). Workspace/status colours are semantic only.
- ❌ **A second purple.** `memory` purple is reserved for 4D memory / WP4. Never use
  purple for anything else, never use AI-purple gradients or neon glows.
- ❌ **Drop shadows as structure.** Use hairline borders.
- ❌ **Rounded/funky display fonts.** Clean system sans only. Mono (`JetBrains Mono` /
  SF Mono) only for traces, metrics, IDs, code.
- ❌ **Emoji as UI decoration.** Icons are FontIcon/SF Symbols, not emoji.
- ❌ **Three-equal-cards** filler layouts and centered-hero-with-gradient clichés.

**Required:**
- ✅ Go through tokens. Never hard-code a hex, radius, or spacing value that a token covers.
- ✅ Both themes. Every surface tested in light and dark.
- ✅ Reuse the shared components before adding new ones.
- ✅ WCAG AA contrast on every text/control; `prefers-reduced-motion` respected;
  motion is `snappy`/`smooth`/`soft` springs, never bouncy.

---

## 3. Cross-client parity & the known web divergence

The three clients must feel like one product. Map tokens, don't reinvent:

| Concept | Tokens.swift | WinUI App.xaml | web styles.css |
|---------|-------------|----------------|----------------|
| accent | `clay` | `AutumnClayBrush` / `SystemAccentColor` | `--accent` |
| sidebar | warm paper | `AutumnSidebarBrush` | `--surface` |
| elevated surface | `surfaceElevated` | `AutumnSurfaceElevatedBrush` | `--surface-elevated` |
| danger | `danger` | `AutumnDangerBrush` | `--danger` |
| radius md | `radius.md` 11 | `AutumnRadiusMD` 11 | `--r-md` 10 |

> **Known divergence — flag, don't silently "fix":** the **web client currently uses a
> dark developer-tool theme** (`--wp1 #818cf8` indigo, `--wp2 #fbbf24` amber,
> `--wp3 #60a5fa` blue, `--bg #0c0c0d`), NOT Paper & Clay. The desktop workspace colours
> are clay / amber / slate / purple. If a task is "make web match desktop", here is the
> intended remap: `--accent → #CC6645`, `--wp1 → #CC6645`, `--wp3 → #527A85`, introduce a
> `--wp4 → #82699E`, and warm the surfaces. **Do not** repaint the web theme as a side
> effect of an unrelated change — call it out and let the user decide scope.

---

## 4. The three dials (pinned restrained for Autumn)

Upstream exposes these as creative range. For Autumn they default **low** because
consistency is the product:

| Dial | Range | Autumn default | Why |
|------|-------|----------------|-----|
| `DESIGN_VARIANCE` | 1–10 | **2** | structured, predictable; a tool, not an Awwwards page |
| `MOTION_INTENSITY` | 1–10 | **3** | subtle springs, pulse on active pipeline stages only |
| `VISUAL_DENSITY` | 1–10 | **5** | calm but information-honest (chat + traces + memory) |

Raise a dial only with an explicit reason tied to the brief. A marketing/landing surface
for Autumn may push `VARIANCE`/`MOTION` higher — the product UI does not.

---

## 5. Pre-flight check (run before declaring done)

- [ ] **Design Read** stated; correct client + theme.
- [ ] Reused existing Autumn components where they exist.
- [ ] Every colour/radius/spacing comes from a token — zero stray hexes.
- [ ] Exactly one accent (clay). No second purple outside 4D memory.
- [ ] No stock platform chrome reintroduced (custom shell intact).
- [ ] Hairline borders, not shadows, carry structure.
- [ ] Light **and** dark both verified.
- [ ] Workspace/status colours used semantically, matching the WP1/2/3/4 map.
- [ ] Contrast AA; reduced-motion honoured; motion uses Autumn spring tokens.
- [ ] If web touched: stayed token-driven; any theme divergence flagged, not silently changed.
- [ ] Cross-client parity considered — would this read as the same product on the other two clients?

---

**Ready?** State the Design Read, confirm the client + surface, then build with the tokens.
