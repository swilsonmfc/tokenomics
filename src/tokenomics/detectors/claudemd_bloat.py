"""D4 — CLAUDE.md bloat: size, duplication, low density."""

from __future__ import annotations

from ..config import Config
from ..model import Corpus
from .base import Finding, Severity


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

        findings: list[Finding] = []
        for doc in docs:
            tokens = doc.get("est_tokens", 0)
            lines = doc.get("lines", 0)
            dup = doc.get("duplicate_headings", [])
            path = doc.get("path", "?")
            over = tokens > th.claudemd_tokens or lines > th.claudemd_lines
            if over or dup:
                sev = Severity.MED if over else Severity.LOW
                # CLAUDE.md is re-sent every turn (cached), so savings compound.
                est_per_turn = max(0, tokens - th.claudemd_tokens)
                findings.append(Finding(
                    detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                    title=f"CLAUDE.md is large: ~{tokens:,} tok / {lines} lines",
                    evidence={
                        "path": path,
                        "est_tokens": tokens,
                        "lines": lines,
                        "duplicate_headings": dup,
                    },
                    est_savings_tokens=est_per_turn,
                    est_savings_weight=est_per_turn / 1_000_000 * 5,
                    recommendation=(
                        "Streamline CLAUDE.md: dedupe sections, drop low-density prose, "
                        "keep imperative rules. It is re-sent (and cache-written) every "
                        "turn, so trimming compounds. See the claude-md-linter skill. "
                        "Editing it mid-session also busts the cache (D5)."
                    ),
                    deep_enrichable=True,
                ))
        return findings


DETECTOR = ClaudeMdBloatDetector()
