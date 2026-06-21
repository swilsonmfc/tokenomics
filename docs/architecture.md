# Architecture

tokenomics turns Claude Code session logs into a token-cost report. The core is
deterministic — no LLM is needed for any hard metric. An optional `--deep` pass adds
cheap-model semantic notes that never alter the numbers.

## Pipeline

```
logpath ──▶ logparse ──▶ assemble ──▶ model ──▶ metrics ──▶ detectors ──▶ report
(discover    (stream      (raw → DAG    (data     (rollups,   (7 analyses,  (aggregates
 session     JSONL,        + subagent    classes)  cost,        Findings)     .json +
 files)      tolerant)     linkage)                cache)                     report.md)
                                                                  ▲
                                       static_analysis ───────────┘ (harness shape)
```

Module responsibilities (`src/tokenomics/`):

| Module | Responsibility |
|---|---|
| `logpath.py` | Map a project path to its `~/.claude/projects/<namespaced>/` dir; discover `<sessionId>.jsonl` + `<sessionId>/subagents/agent-*.jsonl` (+ `.meta.json`). |
| `logparse.py` | Stream JSONL → plain dicts, skipping blank/malformed lines. No interpretation. |
| `model.py` | Frozen/lightweight dataclasses: `TokenUsage`, `ToolCall`, `Turn`, `SubagentRun`, `Session`, `StaticEnv`, `Corpus`. |
| `assemble.py` | Fold raw records into the model; build the conversation DAG; link `tool_use → tool_result → subagent` transcripts. |
| `metrics.py` | Deterministic rollups: totals, cost, cache efficiency, per-model/plugin/skill, context series, subagent reconciliation. |
| `pricing.py` | `TokenUsage → USD` and `→ relative weight`; `normalize_model` strips `[1m]`, provider prefixes, dated suffixes. |
| `config.py` | Paths, `Thresholds`, `MODEL_PRICES`, `MODEL_TIER`; `.tokenomics/config.toml` overrides. |
| `static_analysis/` | Parse the harness: plugins, skills, agents, hooks, MCP, CLAUDE.md → `StaticEnv`. |
| `detectors/` | The 7 analyses; pure functions over `Corpus + Config` → `Finding`s. |
| `report/` | `aggregate.py` orchestrates a scan → `aggregates.json`; `render.py` → `report.md`. |
| `capture/` | Real-time hook: incremental transcript read + threshold flagging. |
| `enrich/deep.py` | Optional LLM enrichment of `deep_enrichable` findings. |
| `cli.py` | `scan | report | mine | promote | capture | watch | reconcile`. |

## Data model

See `model.py`. The shape detectors consume:

- **`TokenUsage`** — `input, output, cache_creation, cache_read, ephemeral_1h/5m,
  web_search/fetch_requests`. Derived: `fresh_input`, `cached_input`, `total_tokens`,
  `context_size` (= input + cache_read + cache_creation, the prompt size that turn).
- **`ToolCall`** — `id, name, is_mcp, mcp_server, input, result_chars, spawned_subagent`.
- **`Turn`** — one assistant/user record: `model, usage, thinking_chars, text_chars,
  tool_calls, is_tool_result, is_sidechain, attribution_plugin/skill`.
- **`SubagentRun`** — `agent_type, description, resolved_model, rollup_total_tokens,
  rollup_usage, tool_stats, turns[]`. `.model` falls back to first transcript model.
- **`Session`** — main-thread `turns[]` + `subagents[]`. **`Corpus`** — sessions + `StaticEnv`.

## Token accounting (the central correctness concern)

1. A turn's `TokenUsage` is read ONLY from top-level `message.usage`. `usage.iterations[]`
   repeats the same counts per streaming iteration — never summed.
2. Subagent tokens are counted ONCE, from the subagent transcript's own turns (the
   authoritative billing basis: each turn re-reads the cache and is billed for it).
3. The parent `toolUseResult.totalTokens` is the subagent's **final-turn usage snapshot**,
   not a sum — so it is legitimately smaller than the transcript total. It is used only by
   `metrics.reconcile_subagents` to cross-check that linkage is correct (final-turn usage
   should match the rollup within tolerance). `tokenomics reconcile` reports this gate.

## Pricing

`config.MODEL_PRICES` (USD per 1M tokens, from the `claude-api` skill): opus $5/$25,
sonnet $3/$15, haiku $1/$5, fable $10/$50. Cache: read ≈0.1×input, write 1.25×(5m)/2×(1h).
Current models (opus 4.6+/sonnet 4.6/fable) are flat-priced at 1M context — the `[1m]`
`resolvedModel` tag is NOT a premium. `pricing.normalize_model` strips `[1m]`,
`us.anthropic.`/`anthropic.` prefixes, and dated `-YYYYMMDD` snapshot suffixes. Every
finding carries savings in both absolute USD (priced models) and a relative weight unit
(so unpriced/unknown models still rank).

## Schema tolerance

Two log generations coexist. The assembler: makes every `usage` sub-key optional; handles
`message.content` as a string OR a list; default-skips unknown record types
(`ai-title, last-prompt, bridge-session, …`); skips `isCompactSummary`/`isApiErrorMessage`
turns for usage. Observed Claude Code `version` values are recorded in `corpus_meta`.
