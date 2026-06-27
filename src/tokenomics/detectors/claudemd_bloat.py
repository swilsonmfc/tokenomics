"""D4 — CLAUDE.md bloat: size, duplication, low density."""

from __future__ import annotations

from collections import Counter

from .. import pricing
from ..config import Config
from ..model import Corpus
from ._util import all_turns
from .base import Confidence, Finding, Severity


class ClaudeMdBloatDetector:
    id = "claudemd_bloat"
    title = "CLAUDE.md hygiene"
    analysis_no = 4

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        docs = corpus.static.claude_md
        if not docs:
            return [Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=Severity.INFO,
                title="No CLAUDE.md found",
                evidence={},
                recommendation="No project/user CLAUDE.md is loaded. That's lean — add "
                               "one only if there's durable guidance worth re-sending each turn.",
            )]

        # CLAUDE.md is re-sent (cache-read) every assistant turn, so the overage
        # cost compounds across the whole corpus, not just once.
        turn_count = 0
        model_tokens: Counter[str] = Counter()
        for turn, default_model, _ in all_turns(corpus):
            if turn.usage and turn.usage.total_tokens:
                turn_count += 1
                model_tokens[pricing.normalize_model(turn.model or default_model)
                             or "unknown"] += turn.usage.total_tokens
        dominant_model = model_tokens.most_common(1)[0][0] if model_tokens else None

        findings: list[Finding] = []
        for doc in docs:
            tokens = doc.get("est_tokens", 0)
            lines = doc.get("lines", 0)
            dup = doc.get("duplicate_headings", [])
            path = doc.get("path", "?")
            over = tokens > th.claudemd_tokens or lines > th.claudemd_lines
            if over or dup:
                sev = Severity.MED if over else Severity.LOW
                est_per_turn = max(0, tokens - th.claudemd_tokens)
                # Overage tokens × turns they were re-sent, priced at the cache-read rate.
                savings = pricing.estimate_savings(
                    est_per_turn * max(turn_count, 1), dominant_model, kind="cache_read",
                    frac=th.claudemd_avoidable_frac, confidence=Confidence.MED)
                findings.append(Finding(
                    detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                    title=f"CLAUDE.md is large: ~{tokens:,} tok / {lines} lines",
                    evidence={
                        "path": path,
                        "est_tokens": tokens,
                        "lines": lines,
                        "overage_per_turn": est_per_turn,
                        "turns_resent": turn_count,
                        "duplicate_headings": dup,
                    },
                    recommendation=(
                        "Streamline CLAUDE.md: dedupe sections, drop low-density prose, "
                        "keep imperative rules. It is re-sent (and cache-written) every "
                        "turn, so trimming compounds. See the tokenomics-advisor-claude skill. "
                        "Editing it mid-session also busts the cache (D5)."
                    ),
                    pattern_id="claudemd.bloat",
                    deep_enrichable=True,
                    **savings,
                ))
        return findings


DETECTOR = ClaudeMdBloatDetector()
