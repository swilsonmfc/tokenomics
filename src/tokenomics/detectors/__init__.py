"""Detector registry. Add a detector module + append it here to enable it."""

from __future__ import annotations

from ..config import Config
from ..model import Corpus
from .base import Detector, Finding, Severity
from .cache_busting import DETECTOR as cache_busting
from .claudemd_bloat import DETECTOR as claudemd_bloat
from .context_window import DETECTOR as context_window
from .review_agents import DETECTOR as review_agents
from .routing import DETECTOR as routing
from .search_efficiency import DETECTOR as search_efficiency
from .second_tier import DETECTOR as second_tier

# Ordered by typical cost-impact (highest, clearest savings first).
REGISTRY: list[Detector] = [
    routing,
    cache_busting,
    context_window,
    search_efficiency,
    review_agents,
    claudemd_bloat,
    second_tier,
]


def run_all(corpus: Corpus, cfg: Config) -> list[Finding]:
    findings: list[Finding] = []
    for det in REGISTRY:
        try:
            findings.extend(det.run(corpus, cfg))
        except Exception as exc:  # a broken detector must not sink the scan
            findings.append(Finding(
                detector_id=getattr(det, "id", "unknown"),
                analysis_no=getattr(det, "analysis_no", 0),
                severity=Severity.INFO,
                title=f"Detector {getattr(det, 'id', '?')} failed",
                evidence={"error": str(exc)},
            ))
    return findings


__all__ = ["REGISTRY", "run_all", "Detector", "Finding", "Severity"]
