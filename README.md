# tokenomics

A Claude Code **plugin** that diagnoses high token costs, discovers savings, and
writes a recommendations report — by mining your `~/.claude/projects/**/*.jsonl`
session logs and static harness config. The analysis core is deterministic and
free; an optional `--deep` pass adds cheap-model semantic notes.

## Quick start

```bash
uv sync --extra dev
uv run python -m tokenomics.cli scan --project /path/to/your/project
# → writes .tokenomics/report.md + aggregates.json
```

As a plugin, use the slash commands: `/tokenomics-scan [--deep]`,
`/tokenomics-report`, `/tokenomics-watch on|off`.

## What it analyzes

The report covers seven savings analyses, each a pluggable detector:

1. **Code-context search efficiency** — grep-heavy trajectories, no indexer
2. **Routing intelligence** — opus-everywhere, trivial work on premium models
3. **Context-window management** — peak/avg size, unused-but-loaded MCP servers
4. **CLAUDE.md hygiene** — bloat, duplication
5. **Cache-busting** — low cache efficiency, prefix invalidation
6. **Review-stage agents** — redundant / over-modeled review passes
7. **Second-tier** — file re-reads, tool-result bloat, fan-out, server-tool waste

Each savings figure is a **scoped, model-aware counterfactual with a confidence tag**:
waste is priced (via `pricing.py`) only on provably-avoidable volume — the busted cache
writes, the repeated greps, the duplicate review runs — and reported as a USD range
(`high`/`med`/`low`), summed by confidence tier rather than as one false "bankable" total.

Beyond the seven curated analyses, `tokenomics mine --all` harvests **candidate** patterns
from your own corpus (expensive vs cheap sessions); `tokenomics promote` graduates the ones
that are stable and well-separated into **empirical** patterns that fire by default.

Four advisory **skills** turn findings into fixes: `tokenomics-advisor-claude`,
`tokenomics-advisor-code-indexing`, `tokenomics-advisor-dynamic-router`, `tokenomics-advisor-context-window`.

A **capture hook** (toggle with `/tokenomics-watch`) flags context growth,
cache-busting, and budget overruns in real time during a session.

## Layout

- `src/tokenomics/` — Python core (parse → model → metrics → detectors → report)
- `commands/`, `hooks/`, `skills/`, `.claude-plugin/` — Claude Code plugin surface
- `tests/` — synthetic-fixture unit tests (`uv run pytest`)

Token accounting counts subagent tokens once (from transcripts), uses top-level
`message.usage` only, and reconciles against the parent rollup as a cross-check.
