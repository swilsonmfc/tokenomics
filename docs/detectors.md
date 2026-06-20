# Detectors

A detector is a pure function over `Corpus + Config` that emits `Finding`s. They live in
`src/tokenomics/detectors/`, implement the `base.Detector` protocol, and are registered in
`detectors/__init__.py REGISTRY` (ordered by typical cost-impact). `run_all` executes them
and isolates failures so one broken detector can't sink a scan.

## The `Finding` model (`base.py`)

```
Finding(detector_id, analysis_no, severity: Severity(INFO|LOW|MED|HIGH),
        title, evidence: dict, est_savings_tokens, est_savings_usd,
        est_savings_weight, recommendation, deep_enrichable, deep_note)
```

`evidence` carries concrete numbers + sample session/turn ids. `deep_enrichable=True` marks
a finding the `--deep` pass may annotate with a semantic note.

## The seven analyses

| # | Module | Detects | Notable thresholds (`config.Thresholds`) |
|---|---|---|---|
| 1 | `search_efficiency` | Search-heavy trajectories, repeated greps, indexer installed-but-unused | `search_ratio` 0.35, `search_min_calls` 8, `repeat_grep` 3 |
| 2 | `routing` | Opus-everywhere (token share), trivial work on a premium model | `opus_share` 0.8, `trivial_output_tokens` 120 |
| 3 | `context_window` | Large peak/avg context, loaded-but-unused MCP servers | `ctx_peak` 150k, `ctx_avg` 80k |
| 4 | `claudemd_bloat` | CLAUDE.md size, duplicate headings (handles absent file = INFO) | `claudemd_tokens` 2000, `claudemd_lines` 200 |
| 5 | `cache_busting` | Low cache efficiency, prefix-invalidation bust turns | `cache_efficiency` 0.60 |
| 6 | `review_agents` | Redundant / over-modeled review subagents | `review_dup` 2 |
| 7 | `second_tier` | Bundle: file re-reads, tool-result bloat, fan-out, server-tool waste | `reread` 3, `fanout` 6, `tool_result_bloat_chars` 50k |

Tier classification for routing/review uses `config.MODEL_TIER` (haiku 1 → fable 4).

## Adding a detector

1. Create `detectors/my_detector.py` with a class exposing `id`, `title`, `analysis_no`
   and `run(self, corpus, cfg) -> list[Finding]`; instantiate `DETECTOR = MyDetector()`.
2. Read thresholds from `cfg.thresholds` (add fields to `config.Thresholds` if needed).
3. Use helpers in `detectors/_util.py` (`all_turns`, `is_search_call`, `looks_review`).
4. Append it to `REGISTRY` in `detectors/__init__.py`.
5. If it maps to a new report section, add it to `report/render.py _ANALYSIS_NAMES`.
6. Add a trigger test + a negative-control test in `tests/test_detectors.py` (pin
   thresholds via the `cfg` fixture).

`second_tier.py` shows the sub-check pattern: a list of small functions each returning an
optional `Finding`, so new second-tier checks slot in without touching the registry.

## The taxonomy matcher (`taxonomy_match.py`)

An eighth registered detector evaluates the **declarative** patterns in the best-practice
catalog against the shared trajectory feature vector — so new coverage can be added as a
catalog entry instead of code. Its findings carry a `pattern_id` and take their
`analysis_no` from the pattern's category. The historical seven also stamp `pattern_id`
to cross-reference their catalog records. See `docs/taxonomy.md`.
