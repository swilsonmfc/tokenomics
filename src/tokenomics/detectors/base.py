"""Detector protocol + Finding model.

A detector reads the assembled Corpus + Config and emits Findings. Detectors are
pure (no I/O) and pluggable: add a module, append it to ``REGISTRY`` in
``__init__``. Thresholds come from ``cfg.thresholds`` so tests can pin them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Protocol, runtime_checkable

from ..config import Config
from ..model import Corpus


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MED = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name


class Confidence(IntEnum):
    """How much to trust a savings estimate.

    HIGH  — real price arithmetic on a provable counterfactual (e.g. the same
            tokens billed at a cheaper model's rate).
    MED   — avoidable volume is well-scoped but the counterfactual is inferred
            (e.g. a re-read that "should" have been one read).
    LOW   — heuristic upper bound / hypothesis (e.g. an index *might* cut greps).
    """

    LOW = 1
    MED = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name


@dataclass
class Finding:
    detector_id: str
    analysis_no: int
    severity: Severity
    title: str
    evidence: dict = field(default_factory=dict)
    est_savings_tokens: int | None = None
    est_savings_usd: float | None = None      # midpoint of the USD range (None = unpriced)
    est_savings_usd_lo: float | None = None
    est_savings_usd_hi: float | None = None
    est_savings_weight: float = 0.0           # model-aware USD-equivalent, for ranking
    confidence: Confidence = Confidence.LOW
    recommendation: str = ""
    deep_enrichable: bool = False
    deep_note: str | None = None  # filled by enrich/deep.py
    pattern_id: str | None = None  # taxonomy pattern this finding instantiates

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = int(self.severity)
        d["severity_label"] = self.severity.label
        d["confidence"] = int(self.confidence)
        d["confidence_label"] = self.confidence.label
        return d


@runtime_checkable
class Detector(Protocol):
    id: str
    title: str
    analysis_no: int

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        ...
