# External taxonomy mining — report

Harvested cost patterns from a supplied list of 20 URLs + GitHub repos and mapped
them onto the tokenomics taxonomy. Output: **3 ready-to-merge declarative patterns**
(validated against `evaluator.py` + the real feature vector) and a **ranked
proposed-feature backlog** of patterns that need new `features.py` signals.

Records live in `mined-external.toml` (repo root, **not** auto-loaded — `load_catalog`
only globs `catalog/*.toml` and `<project>/.tokenomics/taxonomy/*.toml`).

## How to merge

1. **READY patterns** → move the three `[[pattern]]` blocks into
   `src/tokenomics/taxonomy/catalog/` (e.g. append to `core.toml` or a new
   `external.toml`). Two load + fire as-is. `context.session-sprawl` references a new
   threshold — add `long_session_turns: int = 120` to `config.Thresholds` first
   (without it the rule loads but never fires: `evaluate` swallows the NameError).
2. **PROPOSED patterns** → leave in the staging file. They are `engine="declarative"`
   with **no `rule`**, which `_validate` rejects (`"declarative pattern needs a rule"`),
   so they would break `load_catalog` if dropped into `catalog/`. Build the named
   feature, add the rule, *then* merge.
3. Add a trigger + negative-control test in `tests/test_taxonomy.py` per pattern
   (`docs/taxonomy.md` step 3).

Note: `_coerce` filters to known fields, so the `needs_feature` key is dropped on
load — it's documentation only (here + as TOML comments).

## READY — validated declarative patterns

| id | polarity | rule | uses | status |
|----|----------|------|------|--------|
| `search.repeated-grep` | anti | `repeated_search_max >= th.repeat_grep` | existing feature + existing threshold | ready as-is |
| `context.no-subagent-offload` | anti | `ctx_peak >= th.ctx_peak and subagent_count == 0` | existing features + thresholds | ready as-is |
| `context.session-sprawl` | anti | `total_turns >= th.long_session_turns` | existing feature, **new threshold** | add `long_session_turns` |

All three: compiled clean, quiescent at feature defaults (no trivial firing), fired on
their target fixtures, and loaded through the real `load_catalog`.

## PROPOSED — patterns blocked on a new feature (ranked by leverage)

| # | proposed feature(s) | unlocks pattern | sources | notes |
|---|---------------------|-----------------|---------|-------|
| 1 | `noisy_output_share` (low-signal tool/Bash output ÷ total input) | `tooling.noisy-tool-output` | rtk, token-saver, tokensaver, undefdev, headroom, Firecrawl, lean-ctx | **Most-cited theme in the corpus.** Session-aggregate cousin of the per-turn `secondtier.toolresult-bloat` detector. |
| 2 | `input_growth_factor` + `compaction_events` | `context.runaway-history` | clauditor, gsd-core, galando | The real signal behind `context.session-sprawl`; replace `total_turns` proxy once built. clauditor measured waste factor up to 20.1×. |
| 3 | `mcp_tool_count` / `mcp_schema_tokens` | `mcp.tool-surface-bloat` | Reddit best-practices, jcodemunch | Fires even when servers ARE used (vs. `context.unused-mcp`). Hard numbers: 200K→70K window; 16 vs 51+ tools = ~4k vs ~11.5k tok/turn. |
| 4 | `claude_code_version` (already in the JSONL) | `cache.buggy-cc-version` | clauditor | Cheap static parse, high severity: CC 2.1.69–2.1.89 burns 10–20× via a cache bug. |
| 5 | `claudemd_lines` (complements `claudemd_tokens`) | `claudemd.over-line-limit` | oakenai | Cheap. `th.claudemd_lines=200` already exists; only the feature is missing. Memory index past line ~200 is never loaded. |
| 6 | `rework_loops` (edit→run→re-edit on same file) | `workflow.rework-loop` | gsd-core, galando, Reddit | Hardest to compute but high-signal — captures under-specified work redone. |
| 7 | `verbose_prose_turns` (no-tool turns with large output) | `output.verbose-prose` | caveman, claude-token-efficient, claude-token-optimizer | **NEW theme** — verbose *assistant* prose, distinct from tool output. Cheap: the inverse of the trivial-turn check already in `features.py`. No `output` category exists — uses `secondtier` or add one. |
| 8 | `repeated_tool_calls` (identical tool+params re-issued) | `tooling.repeated-tool-calls` | token-optimizer-mcp | Generalizes `repeated_search_max` to any tool/Read. |

## Cross-cutting best-practices worth a `polarity="best_practice"` pass later

Repeatedly endorsed, but they reward behavior that's harder to *detect* than to
*recommend* (candidates if/when the matching features land): prompt-prefix /
KV-cache stabilization (headroom, undefdev — partly covered by `cache.low-efficiency`);
reversible compression + on-demand rehydration (headroom CCR — 73–92% cuts);
partial/symbol-level reads over whole-file reads (lean-ctx, jcodemunch — 92–98%);
durable state artifacts across session boundaries (gsd-core); shared compressed
context across subagents (headroom, lean-ctx).

## Rejected (and why)

- **Proxy/gateway-layer features** — exact + semantic response caching, LLMLingua
  prompt compression, retry/fallback chains, cascading inference, model allowlists
  (Tokenomics-AI, rickcrawford/tokenomics). Real, but they live in an API proxy and
  are **not observable in Claude Code session JSONL** — out of scope for trajectory
  detectors. (Model-tier routing IS covered by `routing.premium-everywhere`.)
- **Budget caps / SLOs / utilization alerts** (lean-ctx, galando) — remediation
  *tooling*, not a detectable behavior.
- **`tugot17/tokenomics`** — off-topic (inference-server throughput benchmarking).
- **No crypto/financial "tokenomics" repos** in the list (checked).

## Captured Medium article — the 10 repos reviewed

All 10 verified real, active (pushed within ~2 weeks), and on-topic. Net: only
**2 new patterns**; the rest reinforce existing/PROPOSED records (strong external
corroboration, not new coverage).

| # | repo | verdict | maps to |
|---|------|---------|---------|
| 1 | rtk-ai/rtk | already harvested | `tooling.noisy-tool-output` |
| 2 | mksglu/context-mode | reinforces | `noisy-tool-output` (tool output → SQLite, query on demand; 98%) |
| 3 | tirth8205/code-review-graph | reinforces | `search.grep-heavy` (Tree-sitter graph; **~82× median, not the article's 49×**) |
| 4 | Mibayy/token-savior | reinforces (composite) | symbol nav + cross-session memory + 34 output compactors |
| 5 | JuliusBrussee/caveman | **NEW** | `output.verbose-prose` (terse-output skill; ~65% output cut) |
| 6 | drona23/claude-token-efficient | **NEW** | `output.verbose-prose` (CLAUDE.md output rules) |
| 7 | ooples/token-optimizer-mcp | **NEW-adjacent** | `tooling.repeated-tool-calls` (repeated-call cache; README says 60–90%, not article's 95%+) |
| 8 | nadimtuhin/claude-token-optimizer | reinforces | `claudemd.bloat` / startup footprint (11K→1.3K confirmed) |
| 9 | alexgreensh/token-optimizer | reinforces | `context.runaway-history` ("ghost tokens" surviving compaction) |
| 10 | zilliztech/claude-context | reinforces | `search.grep-heavy` (BM25+dense retrieval; **~40%, the only quality-gated figure**) |

Caveat: every headline % is self-reported and per-operation/best-case (except #10's
~40%, which is quality-controlled). The article inflates/misstates several figures vs.
the repos' own READMEs (#3, #7) — the repos are more conservative than the article.

## Source access notes

- **Medium "10 GitHub repos…"** — paywalled; only ~1 of the 10 repos was visible. Most
  of those repos appear elsewhere in the list and were read directly.
- **All four Reddit URLs** — blocked to WebFetch; substance recovered via WebSearch,
  so several Reddit-derived records rest on search snippets, not verbatim pages (lower
  confidence; flagged inline). The clauditor + GitHub repos were fetched directly.
- Per-repo benchmark percentages are the repos' **own self-reported** figures, not
  independently verified.

## Suggested next step

Build feature **#1 (`noisy_output_share`)** — highest corpus support, and it upgrades
the existing per-turn tool-bloat detector into a session-level signal. Then re-run a
scan to see which of the READY patterns actually fire on your own corpus (the natural
hand-off to the empirical miner: external hypothesis → confirmed on your data).
