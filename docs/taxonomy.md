# Best-practice taxonomy

The taxonomy is the single, declarative knowledge source for cost patterns —
both anti-patterns and best practices. It turns knowledge that used to be
scattered across detector code, threshold constants, and skill prose into one
catalog the whole pipeline pattern-matches against.

## Pieces

```
features.py ─────────▶ TrajectoryFeatures   (one normalized signal vector / corpus)
taxonomy/catalog/*.toml ─▶ Catalog           (Pattern records: anti-pattern | best-practice)
taxonomy/evaluator.py ──▶ safe rule eval     (boolean expr over the feature namespace)
detectors/taxonomy_match.py ─▶ matcher       (fires declarative patterns → Findings)
```

- **`features.py`** computes a flat, serializable feature vector once (search ratio,
  premium token share, cache efficiency, context peak, reread count, premium-subagent
  runs, unused MCP, …). It is the substrate both the matcher and (next phase) the
  corpus miner read. Pure, no `detectors` import (avoids an import cycle).
- **`taxonomy/catalog/*.toml`** holds one `[[pattern]]` per cost pattern. Drop a TOML
  file in this dir to extend the catalog — no code.
- **`evaluator.py`** sandboxes declarative rules: no builtins, no dunder access, rules
  compiled at load time so a malformed rule fails the scan loudly, not silently.
- **`detectors/taxonomy_match.py`** is the engine: compute features, evaluate every
  declarative pattern's rule, emit a `Finding` carrying its `pattern_id`.

## The `Pattern` record

```
id              routing.thinking-on-trivial
category        routing            # → report analysis_no via CATEGORY_ANALYSIS
polarity        anti_pattern | best_practice
scope           turn | trajectory | session | static | corpus
engine          detector | declarative
rule            "thinking_trivial_turns >= th.thinking_trivial"   # declarative only
detector_id     routing                                           # detector only
signals         ["thinking_trivial_turns"]   # feature names surfaced as evidence
severity        info | low | med | high      # declarative only
remediation_skill  dynamic-router-advisor
maturity        curated | empirical | candidate
provenance / reviewed                          # where it came from, when last checked
```

## Two engines

- **`detector`** — computed by a bespoke Python detector (the historical seven). The
  catalog record is metadata + the cross-reference: the detector stamps
  `Finding.pattern_id`, so report, skills, and aggregates speak one vocabulary.
- **`declarative`** — a boolean `rule` over the feature vector, evaluated by the matcher.
  New coverage with zero bespoke code (e.g. `routing.thinking-on-trivial`,
  `routing.premium-subagents`).

## Maturity tiers (trust gate)

`curated` (authoritative — Anthropic/Claude Code docs, the `claude-api` skill),
`empirical` (corpus-mined and confirmed), `candidate` (mined, unconfirmed). The
corpus miner that emits `candidate` records — contrasting high- vs low-efficiency
sessions over the feature vector — is the next phase; the schema and the feature
substrate are already in place for it. Every pattern carries `provenance`/`reviewed`
so curated knowledge can be re-checked as models and pricing change.

## Adding a pattern

1. **Declarative:** add a `[[pattern]]` with a `rule` to `catalog/core.toml` (or a new
   `*.toml`). Reference feature names + `th.<threshold>`. Add the threshold to
   `config.Thresholds` if new. Done — the matcher picks it up.
2. **Detector-backed:** add the detector as usual (`docs/detectors.md`), set
   `pattern_id=` on its Finding, and add a matching `engine = "detector"` record.
3. Add a trigger + negative-control test in `tests/test_taxonomy.py`.

## Output

`aggregates.json` gains `trajectory_features` (the vector) and `taxonomy`
(`catalog_size`, `by_maturity`, `matched_patterns`). The report gains a **Taxonomy
coverage** section, and each finding shows its `🧬 taxonomy: <id>` tag.
