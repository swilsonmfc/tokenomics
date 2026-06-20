"""D5 — Cache-busting behaviors: low cache efficiency, prefix invalidation."""

from __future__ import annotations

from collections import Counter

from .. import pricing
from ..config import Config
from ..model import Corpus
from ._util import all_turns
from .base import Confidence, Finding, Severity


def _busted_savings(bust_turns: list[dict], frac: tuple[float, float]) -> dict | None:
    """Savings = the cache-write-over-read premium on busted volume, by model.

    A bust re-writes a prefix that should have stayed cache-readable, so the
    avoidable cost is the *premium* of a write over the read it replaced — not
    the gross write volume. Priced per-model and summed.
    """
    busted_by_model: Counter[str] = Counter()
    for b in bust_turns:
        busted_by_model[b["model"] or "unknown"] += b["cache_creation"]
    if not busted_by_model:
        return None
    merged = {
        "est_savings_tokens": 0, "est_savings_weight": 0.0,
        "est_savings_usd": None, "est_savings_usd_lo": None, "est_savings_usd_hi": None,
        "confidence": Confidence.MED,
    }
    any_usd = False
    for model, tokens in busted_by_model.items():
        s = pricing.estimate_savings(
            tokens, model, kind="cache_premium", frac=frac, confidence=Confidence.MED)
        merged["est_savings_tokens"] += s["est_savings_tokens"]
        merged["est_savings_weight"] += s["est_savings_weight"]
        if s["est_savings_usd"] is not None:
            any_usd = True
            for k in ("est_savings_usd", "est_savings_usd_lo", "est_savings_usd_hi"):
                merged[k] = round((merged[k] or 0.0) + s[k], 4)
    if not any_usd:
        for k in ("est_savings_usd", "est_savings_usd_lo", "est_savings_usd_hi"):
            merged[k] = None
    return merged


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
        # Savings are claimed ONLY on turns we can point to as busts (write that
        # should have been a read), never on all cache creation — most of which
        # is the legitimate, unavoidable first write of a stable prefix.
        savings = _busted_savings(bust_turns, th.cache_bust_avoidable_frac) or {}
        if efficiency < th.cache_efficiency:
            sev = Severity.HIGH if efficiency < th.cache_efficiency * 0.7 else Severity.MED
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                title=f"Low cache efficiency: {efficiency:.0%} reads vs writes",
                evidence={
                    "efficiency": round(efficiency, 3),
                    "total_cache_read": total_read,
                    "total_cache_creation": total_create,
                    "bust_turn_count": len(bust_turns),
                    "busted_creation_tokens": sum(b["cache_creation"] for b in bust_turns),
                    "sample_busts": bust_turns[:5],
                },
                recommendation=(
                    "High cache-write vs cache-read means the prompt prefix keeps "
                    "changing. Avoid mid-session edits to CLAUDE.md / system prompt / "
                    "tool set, keep volatile content (timestamps, IDs) after the last "
                    "cache breakpoint, and serialize tool lists deterministically."
                ),
                pattern_id="cache.low-efficiency",
                **savings,
            ))
        elif bust_turns:
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=Severity.LOW,
                title=f"{len(bust_turns)} cache-bust turns despite healthy overall efficiency",
                evidence={"efficiency": round(efficiency, 3),
                          "sample_busts": bust_turns[:5]},
                recommendation="Investigate the prefix change at the flagged turns.",
                pattern_id="cache.low-efficiency",
                **savings,
            ))
        return findings


DETECTOR = CacheBustingDetector()
