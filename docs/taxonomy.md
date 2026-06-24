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
`empirical` (corpus-mined and confirmed), `candidate` (mined, unconfirmed). Every
pattern carries `provenance`/`reviewed` so curated knowledge can be re-checked as
models and pricing change.

## Empirical mining (`miner.py`, `tokenomics mine`)

The miner *harvests* candidate patterns from the corpus instead of hand-coding them:

1. Score each session by **cost intensity** — relative weight per 1k output tokens
   (works for unpriced models; higher = worse). Sessions with too little output to
   score are dropped.
2. Split the corpus into an **expensive** (top-quartile) and **cheap** (bottom-quartile)
   cohort.
3. For each behavioural signal in `MINEABLE`, test whether its cohort medians separate
   by ≥ `mine_min_separation` of the signal's observed range, in the worsening
   direction. A signal that does becomes a `candidate` `Pattern` with a data-derived
   threshold (the midpoint of the two medians).

Output: `.tokenomics/mined.json`, `.tokenomics/mined-report.md` (candidate table +
per-session benchmark), and `.tokenomics/taxonomy/mined.toml` (the candidate records,
in catalog format). `load_catalog(project_path=…)` picks that file up, so candidates
ride along on later scans — but the matcher **ignores `candidate` patterns unless
`match_candidate_patterns = true`** (they're correlational until promoted).

It is deterministic and stdlib-only (no ML); output is correlational, so confounders
(a session may be expensive because it was *long*, not *badly routed*) are why the
trust gate exists. Run `tokenomics mine --all` to pool sessions across projects — more
data, sharper cohorts. Mining needs ≥ `mine_min_sessions` scorable sessions.

### Matching `session`-scoped rules

Mined thresholds are fit on the **per-session** distribution, so a mined (`scope =
"session"`) rule is judged the same way: the matcher evaluates it against each session's
feature vector and fires only if it holds in ≥ `mine_session_hit_ratio` of sessions (the
finding records `session_hit_ratio`). Curated `scope = "trajectory"` rules still evaluate
against the corpus-level vector. This is what lets a threshold like `bust_turns >= 4`
mean the same thing at match time as it did at mine time — summed corpus counts no longer
make every mined rule fire trivially.

### Promotion: `candidate` → `empirical`

`tokenomics promote --project <p> [--all-qualifying | <pattern_id>…]` turns a reviewed
candidate into a trusted `empirical` record that fires **by default** (no opt-in). A
candidate qualifies only if it (1) **reappears** when the current corpus is re-mined
(stability) and (2) separates at ≥ `promote_min_separation`. Qualifying records move from
`mined.toml` into `promoted.toml` with their id renamed `mined.*` → `empirical.*` and
`maturity` flipped; the rest stay as candidates. Nothing is promoted that a fresh mine of
today's data does not still support.

## Adding a pattern

1. **Declarative:** add a `[[pattern]]` with a `rule` to `catalog/core.toml` (or a new
   `*.toml`, e.g. `catalog/external.toml` holds the patterns mined from external
   docs/repos — see `mined-external-report.md` for their provenance). Reference
   feature names + `th.<threshold>`. Add the threshold to `config.Thresholds` if new.
   Done — the matcher picks it up.
2. **Detector-backed:** add the detector as usual (`docs/detectors.md`), set
   `pattern_id=` on its Finding, and add a matching `engine = "detector"` record.
3. Add a trigger + negative-control test in `tests/test_taxonomy.py`.

## Output

`aggregates.json` gains `trajectory_features` (the vector) and `taxonomy`
(`catalog_size`, `by_maturity`, `matched_patterns`). The report gains a **Taxonomy
coverage** section, and each finding shows its `🧬 taxonomy: <id>` tag.
