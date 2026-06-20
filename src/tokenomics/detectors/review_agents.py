"""D6 — Review stages via agents: redundancy, over-modeling, fan-out."""

from __future__ import annotations

from collections import defaultdict

from ..config import MODEL_TIER, Config
from ..metrics import subagent_usage
from ..model import Corpus
from ._util import looks_review
from .base import Finding, Severity


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

        # Redundant reviews: same review agent_type repeated within a session.
        per_session_types: dict[str, list[str]] = defaultdict(list)
        for sid, sub in review_runs:
            per_session_types[sid].append(sub.agent_type or sub.description or "review")
        redundant = {
            sid: types for sid, types in per_session_types.items()
            if len(types) - len(set(types)) >= th.review_dup - 1 and len(types) > len(set(types))
        }

        # Over-modeled reviews: review agent on a top-tier model.
        over_modeled = [
            (sid, sub.agent_type or sub.description, sub.model)
            for sid, sub in review_runs
            if MODEL_TIER.get((sub.model or "").replace("[1m]", ""), 0) >= 3
        ]

        findings.append(Finding(
            detector_id=self.id, analysis_no=self.analysis_no,
            severity=Severity.MED if (redundant or over_modeled) else Severity.INFO,
            title=f"{len(review_runs)} review/critique subagent run(s)",
            evidence={
                "review_run_count": len(review_runs),
                "total_review_tokens": total_review_tokens,
                "redundant_sessions": list(redundant.keys()),
                "over_modeled_count": len(over_modeled),
            },
            est_savings_tokens=total_review_tokens // 4 if (redundant or over_modeled) else None,
            recommendation=(
                "Consolidate duplicate review passes and run reviews on a cheaper "
                "model where a premium one isn't needed; fan out only when reviews "
                "are genuinely independent."
            ),
            deep_enrichable=True,
        ))
        return findings


DETECTOR = ReviewAgentsDetector()
