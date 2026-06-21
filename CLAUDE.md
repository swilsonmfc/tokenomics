# tokenomics

Claude Code **plugin** (Python 3.12 core) that diagnoses token cost from
`~/.claude/projects/**/*.jsonl` session logs + static harness config, and writes a
`.tokenomics/` report into the analyzed project. Deterministic core; optional `--deep`
LLM pass for semantic notes only.

## Commands

```bash
uv sync --extra dev                                   # set up env
uv run pytest                                         # 94 tests (3 skip w/o real logs)
uv run ruff check src/ tests/                         # lint
uv run python -m tokenomics.cli scan --project <path> # run a scan
uv run python -m tokenomics.cli mine --project <path> --all  # harvest candidate patterns
uv run python -m tokenomics.cli promote --project <path> --all-qualifying  # candidate→empirical
uv run python -m tokenomics.cli reconcile --project <path>  # P1 token-accounting gate
```

## Where things live

- `src/tokenomics/` — core pipeline: `logpath → logparse → assemble → model → metrics
  → detectors → report`. See `docs/architecture.md`.
- `src/tokenomics/detectors/` — the 7 analyses + the taxonomy matcher, registered in
  `__init__.py REGISTRY`. See `docs/detectors.md`.
- `src/tokenomics/features.py` + `taxonomy/` — shared trajectory feature vector + the
  declarative best-practice catalog matched against it. `miner.py` harvests `candidate`
  patterns from the corpus (the `mine` command). See `docs/taxonomy.md`.
- `src/tokenomics/static_analysis/` — parses plugins/skills/agents/hooks/MCP/CLAUDE.md.
- `src/tokenomics/capture/` — real-time hook (reads live transcript incrementally).
- `src/tokenomics/enrich/deep.py` — optional `--deep` pass (additive only).
- `commands/`, `hooks/`, `skills/`, `.claude-plugin/` — plugin surface. See `docs/plugin.md`.
- `tests/` — synthetic-fixture unit tests; builders in `conftest.py`.

## Invariants (do not break)

- Token usage comes ONLY from top-level `message.usage`, never `usage.iterations[]`.
- Subagent tokens are counted ONCE from transcripts. `toolUseResult.totalTokens` is the
  subagent's FINAL-turn snapshot (not a sum) — used only to cross-check linkage.
- Detectors are pure (no I/O); thresholds live in `config.Thresholds` so tests pin them.
- Savings go through `pricing.estimate_savings` (model-aware USD + range + `confidence`) on
  *provably-avoidable* volume only — never a hardcoded multiplier or "all of X". The report
  sums by confidence tier, never one bankable total.
- Pricing lives in `config.MODEL_PRICES`, sourced from the `claude-api` skill — update it
  there, not from memory. `[1m]` is not a price premium on current models.
- Keep this file lean: it is re-sent every turn and the project's own linter flags bloat.

## Reference docs

- `docs/architecture.md` — pipeline, data model, token accounting
- `docs/log-format.md` — the Claude Code session JSONL schema (signal source)
- `docs/detectors.md` — the 7 detectors + how to add one
- `docs/taxonomy.md` — feature vector + declarative best-practice catalog
- `docs/plugin.md` — commands, capture hook, advisory skills
- `docs/development.md` — workflow, testing, conventions
