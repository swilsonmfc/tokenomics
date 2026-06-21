"""Empirical pattern miner (Phase B).

Discovers cost patterns from the corpus instead of hand-coding them: it scores
each session by cost intensity (relative weight per unit of output), splits the
corpus into an *expensive* and a *cheap* cohort by quartile, then asks which
behavioural signals separate the two. A signal that is reliably elevated (or, for
cache efficiency, depressed) in the expensive cohort becomes a ``candidate``
pattern with a data-derived threshold.

Deliberately conservative and explainable — no ML, stdlib statistics only,
deterministic. Output is correlational, so every emitted pattern carries
``maturity = "candidate"``: surfaced for review, not auto-promoted into findings
(see ``Config.match_candidate_patterns``). Confounders are real (a session may be
expensive because it was *long*, not *badly routed*), which is exactly why these
need confirmation before they harden into curated/empirical records.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import Config
from .features import TrajectoryFeatures, compute_session_features
from .model import Corpus
from .taxonomy import Pattern


@dataclass(frozen=True)
class SignalSpec:
    feature: str
    label: str
    category: str
    higher_is_worse: bool = True
    remediation_skill: str | None = None
    is_int: bool = False


# The behavioural signals the miner is allowed to test. Excludes the outcome
# inputs (weight/output/total_tokens) to avoid circularity, and the static
# signals (unused_mcp, agent pins) which don't vary across a project's sessions.
MINEABLE: list[SignalSpec] = [
    SignalSpec("search_ratio", "search-heavy", "search", True, "code-indexing-advisor"),
    SignalSpec("premium_token_share", "premium-model share", "routing", True,
               "dynamic-router-advisor"),
    SignalSpec("trivial_premium_ratio", "trivial-on-premium rate", "routing", True,
               "dynamic-router-advisor"),
    SignalSpec("thinking_trivial_turns", "thinking-on-trivial turns", "routing", True,
               "dynamic-router-advisor", is_int=True),
    SignalSpec("ctx_peak", "context peak", "context", True, "context-window-evaluator",
               is_int=True),
    SignalSpec("ctx_avg", "context average", "context", True, "context-window-evaluator"),
    SignalSpec("reread_files", "file re-reads", "secondtier", True, is_int=True),
    SignalSpec("max_fanout", "subagent fan-out", "secondtier", True, is_int=True),
    SignalSpec("web_requests", "web search/fetch", "secondtier", True, is_int=True),
    SignalSpec("bust_turns", "cache-bust turns", "cache", True, is_int=True),
    SignalSpec("premium_subagent_runs", "premium subagents", "routing", True,
               "dynamic-router-advisor", is_int=True),
    SignalSpec("cache_efficiency", "cache efficiency", "cache", False),
]


@dataclass
class MinedFinding:
    feature: str
    label: str
    category: str
    bad_median: float
    good_median: float
    separation: float
    suggested_threshold: float
    n_bad: int
    n_good: int
    pattern: Pattern

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in (
            "feature", "label", "category", "bad_median", "good_median",
            "separation", "suggested_threshold", "n_bad", "n_good")}
        d["pattern_id"] = self.pattern.id
        d["severity"] = self.pattern.severity
        d["rule"] = self.pattern.rule
        return d


@dataclass
class MineReport:
    mined: bool = False
    reason: str = ""
    session_count: int = 0
    included_count: int = 0
    outcome_name: str = "relative weight per 1k output tokens"
    cheap_boundary: float = 0.0
    expensive_boundary: float = 0.0
    findings: list[MinedFinding] = field(default_factory=list)
    benchmark: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mined": self.mined,
            "reason": self.reason,
            "session_count": self.session_count,
            "included_count": self.included_count,
            "outcome_name": self.outcome_name,
            "cheap_boundary": round(self.cheap_boundary, 4),
            "expensive_boundary": round(self.expensive_boundary, 4),
            "findings": [f.to_dict() for f in self.findings],
            "benchmark": self.benchmark,
        }

    def patterns(self) -> list[Pattern]:
        return [f.pattern for f in self.findings]


def _outcome(feats: TrajectoryFeatures) -> float:
    """Cost intensity: relative weight per 1k output tokens (higher = worse)."""
    return feats.weight / max(feats.output_tokens, 1) * 1000.0


def _threshold(spec: SignalSpec, lo: float, hi: float) -> float:
    mid = (lo + hi) / 2.0
    return float(round(mid)) if spec.is_int else round(mid, 4)


def _synthesize(spec: SignalSpec, threshold: float, separation: float,
                bad_med: float, good_med: float, n: int, today: str) -> Pattern:
    op = ">=" if spec.higher_is_worse else "<="
    sev = "med" if separation >= 0.35 else "low"
    if spec.higher_is_worse:
        title = f"Expensive sessions show elevated {spec.label}"
        rec = (f"Your most cost-intensive sessions run {spec.label} at/above "
               f"{threshold:g} (vs {good_med:g} in cheap sessions). Review before promoting.")
    else:
        title = f"Expensive sessions show depressed {spec.label}"
        rec = (f"Your most cost-intensive sessions run {spec.label} at/below "
               f"{threshold:g} (vs {good_med:g} in cheap sessions). Review before promoting.")
    return Pattern(
        id=f"mined.{spec.feature}",
        category=spec.category,
        polarity="anti_pattern",
        scope="session",
        engine="declarative",
        rule=f"{spec.feature} {op} {threshold:g}",
        signals=(spec.feature,),
        severity=sev,
        remediation_skill=spec.remediation_skill,
        maturity="candidate",
        provenance=(f"empirical: mined from {n} sessions (expensive vs cheap quartile), "
                    f"median {bad_med:g} vs {good_med:g}, separation {separation:.2f}"),
        reviewed=today,
        title=title,
        recommendation=rec,
    )


def mine(corpus: Corpus, cfg: Config, today: str = "") -> MineReport:
    th = cfg.thresholds
    scored: list[tuple[float, object, TrajectoryFeatures]] = []
    for s in corpus.sessions:
        feats = compute_session_features(s, corpus.static, cfg)
        if feats.output_tokens < th.mine_min_session_output:
            continue
        scored.append((_outcome(feats), s, feats))

    report = MineReport(session_count=len(corpus.sessions), included_count=len(scored))
    if len(scored) < th.mine_min_sessions:
        report.reason = (f"need ≥{th.mine_min_sessions} sessions with ≥"
                         f"{th.mine_min_session_output} output tokens; have {len(scored)}")
        return report

    outcomes = sorted(o for o, _, _ in scored)
    q1, _, q3 = statistics.quantiles(outcomes, n=4)
    report.cheap_boundary, report.expensive_boundary = q1, q3

    cheap = [f for o, _, f in scored if o <= q1]
    expensive = [f for o, _, f in scored if o >= q3]
    if len(cheap) < th.mine_min_cohort or len(expensive) < th.mine_min_cohort:
        report.reason = "cohorts too small after quartile split"
        return report

    for spec in MINEABLE:
        all_vals = [getattr(f, spec.feature) for _, _, f in scored]
        rng = max(all_vals) - min(all_vals)
        if rng <= 0:
            continue
        bad = [getattr(f, spec.feature) for f in expensive]
        good = [getattr(f, spec.feature) for f in cheap]
        bad_med, good_med = statistics.median(bad), statistics.median(good)
        directional = (bad_med > good_med) if spec.higher_is_worse else (bad_med < good_med)
        if not directional:
            continue
        separation = abs(bad_med - good_med) / rng
        if separation < th.mine_min_separation:
            continue
        threshold = _threshold(spec, good_med, bad_med)
        pattern = _synthesize(spec, threshold, separation, bad_med, good_med,
                              len(scored), today)
        report.findings.append(MinedFinding(
            feature=spec.feature, label=spec.label, category=spec.category,
            bad_median=round(bad_med, 4), good_median=round(good_med, 4),
            separation=round(separation, 4), suggested_threshold=threshold,
            n_bad=len(expensive), n_good=len(cheap), pattern=pattern,
        ))

    report.findings.sort(key=lambda f: -f.separation)
    report.mined = True

    ranked = sorted(scored, key=lambda t: -t[0])
    n = len(ranked)
    report.benchmark = [
        {"session": s.session_id, "outcome": round(o, 4),
         "percentile": round(100 * (n - i) / n), "top_model": f.top_model}
        for i, (o, s, f) in enumerate(ranked[:15])
    ]
    return report
