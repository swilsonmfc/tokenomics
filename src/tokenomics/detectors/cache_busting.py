"""D5 — Cache-busting behaviors: low cache efficiency, prefix invalidation."""

from __future__ import annotations

from .. import pricing
from ..config import Config
from ..model import Corpus
from ._util import all_turns
from .base import Finding, Severity


class CacheBustingDetector:
    id = "cache_busting"
    title = "Cache-busting behavior"
    analysis_no = 5

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        total_read = 0
        total_create = 0
        bust_turns: list[dict] = []

        for turn, default_model, session in all_turns(corpus):
            u = turn.usage
            if u is None:
                continue
            total_read += u.cache_read
            total_create += u.cache_creation
            # A bust: large fresh cache write with near-zero read (prefix changed).
            if u.cache_creation > 5000 and u.cache_read < u.cache_creation * 0.2:
                bust_turns.append({
                    "session": session.session_id,
                    "uuid": turn.uuid,
                    "cache_creation": u.cache_creation,
                    "cache_read": u.cache_read,
                    "model": pricing.normalize_model(turn.model or default_model),
                })

        denom = total_read + total_create
        if denom == 0:
            return []
        efficiency = total_read / denom

        findings: list[Finding] = []
        if efficiency < th.cache_efficiency:
            # Wasted = the cache-write premium over a cache-read on busted volume.
            wasted_tokens = total_create
            sev = Severity.HIGH if efficiency < th.cache_efficiency * 0.7 else Severity.MED
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                title=f"Low cache efficiency: {efficiency:.0%} reads vs writes",
                evidence={
                    "efficiency": round(efficiency, 3),
                    "total_cache_read": total_read,
                    "total_cache_creation": total_create,
                    "bust_turn_count": len(bust_turns),
                    "sample_busts": bust_turns[:5],
                },
                est_savings_tokens=wasted_tokens,
                est_savings_weight=wasted_tokens / 1_000_000 * 5 * 1.15,
                recommendation=(
                    "High cache-write vs cache-read means the prompt prefix keeps "
                    "changing. Avoid mid-session edits to CLAUDE.md / system prompt / "
                    "tool set, keep volatile content (timestamps, IDs) after the last "
                    "cache breakpoint, and serialize tool lists deterministically."
                ),
            ))
        elif bust_turns:
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=Severity.LOW,
                title=f"{len(bust_turns)} cache-bust turns despite healthy overall efficiency",
                evidence={"efficiency": round(efficiency, 3),
                          "sample_busts": bust_turns[:5]},
                est_savings_tokens=sum(b["cache_creation"] for b in bust_turns),
                recommendation="Investigate the prefix change at the flagged turns.",
            ))
        return findings


DETECTOR = CacheBustingDetector()
