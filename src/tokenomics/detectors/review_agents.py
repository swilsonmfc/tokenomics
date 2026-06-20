"""D6 — Review stages via agents: redundancy, over-modeling, fan-out."""

from __future__ import annotations

from collections import defaultdict

from .. import pricing
from ..config import MODEL_TIER, Config
from ..metrics import subagent_usage
from ..model import Corpus
from ._util import looks_review
from .base import Confidence, Finding, Severity

# Realistic cheaper tier for review work when a premium model was used.
_REVIEW_DOWNGRADE = "claude-sonnet-4-6"


class ReviewAgentsDetector:
    id = "review_agents"
    title = "Review-stage agents"
    analysis_no = 6

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        review_runs = []
        for session in corpus.sessions:
            for sub in session.subagents:
                if looks_review(sub.agent_type) or looks_review(sub.description):
                    review_runs.append((session.session_id, sub))

        if not review_runs:
            return []

        findings: list[Finding] = []
        total_review_tokens = sum(subagent_usage(s).total_tokens for _, s in review_runs)

        # Redundant reviews: the duplicate runs (everything past the first of each
        # review type within a session) are the directly-avoidable volume.
        seen: dict[str, set[str]] = defaultdict(set)
        dup_subs = []
        dup_sessions: set[str] = set()
        for sid, sub in review_runs:
            t = sub.agent_type or sub.description or "review"
            if t in seen[sid]:
                dup_subs.append(sub)
                dup_sessions.add(sid)
            else:
                seen[sid].add(t)
        redundant_sessions = sorted(dup_sessions)
        redundant_tokens = sum(subagent_usage(s).total_tokens for s in dup_subs)
        redundant_cost = sum(pricing.usage_cost_usd(subagent_usage(s), s.model) or 0.0
                             for s in dup_subs)
        redundant_weight = sum(pricing.usage_weight(subagent_usage(s), s.model)
                               for s in dup_subs)

        # Over-modeled reviews: same work re-priced at a cheaper tier — the saving
        # is the price *delta*, not a token reduction.
        over_runs = [s for _, s in review_runs
                     if MODEL_TIER.get((s.model or "").replace("[1m]", ""), 0) >= 3]
        om_delta = 0.0
        om_weight = 0.0
        for s in over_runs:
            u = subagent_usage(s)
            cur = pricing.usage_cost_usd(u, s.model)
            cheap = pricing.usage_cost_usd(u, _REVIEW_DOWNGRADE)
            if cur is not None and cheap is not None:
                om_delta += max(0.0, cur - cheap)
            om_weight += max(0.0, pricing.usage_weight(u, s.model)
                             - pricing.usage_weight(u, _REVIEW_DOWNGRADE))

        actionable = bool(dup_subs or over_runs)
        savings: dict = {}
        if actionable:
            lo_f, hi_f = th.review_redundant_frac
            mid_f = (lo_f + hi_f) / 2.0
            priced = redundant_cost > 0 or om_delta > 0
            usd_lo = round(redundant_cost * lo_f + om_delta, 4) if priced else None
            usd_hi = round(redundant_cost * hi_f + om_delta, 4) if priced else None
            usd_mid = round(redundant_cost * mid_f + om_delta, 4) if priced else None
            savings = {
                "est_savings_tokens": int(redundant_tokens * mid_f) or None,
                "est_savings_usd": usd_mid,
                "est_savings_usd_lo": usd_lo,
                "est_savings_usd_hi": usd_hi,
                "est_savings_weight": redundant_weight * mid_f + om_weight,
                "confidence": Confidence.MED,
            }

        findings.append(Finding(
            detector_id=self.id, analysis_no=self.analysis_no,
            severity=Severity.MED if actionable else Severity.INFO,
            title=f"{len(review_runs)} review/critique subagent run(s)",
            evidence={
                "review_run_count": len(review_runs),
                "total_review_tokens": total_review_tokens,
                "duplicate_run_count": len(dup_subs),
                "redundant_sessions": redundant_sessions,
                "redundant_tokens": redundant_tokens,
                "over_modeled_count": len(over_runs),
            },
            recommendation=(
                "Consolidate duplicate review passes and run reviews on a cheaper "
                "model where a premium one isn't needed; fan out only when reviews "
                "are genuinely independent."
            ),
            pattern_id="review.redundant-or-overmodeled",
            deep_enrichable=True,
            **savings,
        ))
        return findings


DETECTOR = ReviewAgentsDetector()
