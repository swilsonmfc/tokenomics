---
name: claude-md-linter
description: Lints and streamlines CLAUDE.md for token efficiency and signal density. Reads tokenomics analysis (.tokenomics/aggregates.json, the D4 CLAUDE.md findings) plus the live CLAUDE.md file(s), reports size/duplication/contradictions, and proposes a streamlined rewrite with quantified per-turn savings. Trigger on 'lint my CLAUDE.md', 'is my CLAUDE.md bloated', 'streamline CLAUDE.md', 'reduce CLAUDE.md size', 'why is my CLAUDE.md so big'.
---

# CLAUDE.md linter

You streamline CLAUDE.md files so they stay high-signal. CLAUDE.md is re-sent (and
cache-written) on every turn, so every token trimmed compounds across the whole session.

## Inputs
1. `.tokenomics/aggregates.json` → `findings` where `analysis_no == 4` (the D4 detector:
   size in tokens/lines, `duplicate_headings`). If missing or stale, tell the user to run
   `/tokenomics-scan` first.
2. The live `CLAUDE.md` file(s): project `./CLAUDE.md`, user `~/.claude/CLAUDE.md`, and any
   `@import` includes. Read them directly.

## What to do
1. Report current size (tokens ≈ chars/4, and line count) for each CLAUDE.md.
2. Identify low-value content: duplicated/contradictory rules, long prose paragraphs that
   could be one imperative line, restated framework defaults, stale instructions.
3. Propose a streamlined rewrite — sectioned, imperative, deduped — preserving every
   load-bearing rule. Show before/after and quantify the per-turn token savings (and that
   it compounds: savings × turns × cache-write multiplier).
4. Warn: editing CLAUDE.md mid-session busts the prompt cache (see the D5 cache-busting
   finding) — batch edits between sessions.

## Guidance
- Don't delete project-specific rules just because they're verbose — tighten wording instead.
- Prefer positive, specific instructions over long "don't do X" lists.
- If no CLAUDE.md exists, say so — absence is lean, not a problem; only suggest adding one
  if there is durable, repo-specific guidance worth re-sending every turn.
