"""Taxonomy matcher — evaluates declarative catalog patterns against features.

This is the "pattern match against a taxonomy" engine: it computes the shared
trajectory feature vector once, then fires every declarative pattern whose rule
holds. Detector-backed patterns are handled by their own modules (which stamp
``Finding.pattern_id``); this detector only emits the declarative ones, so adding
a new declarative pattern is a catalog edit, not a code change.
"""

from __future__ import annotations

from ..config import Config
from ..features import compute_features
from ..model import Corpus
from ..taxonomy import load_catalog
from ..taxonomy.evaluator import evaluate
from .base import Finding, Severity

_SEV = {"info": Severity.INFO, "low": Severity.LOW, "med": Severity.MED, "high": Severity.HIGH}


class TaxonomyMatchDetector:
    id = "taxonomy_match"
    title = "Taxonomy pattern match"
    analysis_no = 0  # per-finding analysis_no comes from the pattern's category

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        catalog = load_catalog(project_path=corpus.project_path)
        feats = compute_features(corpus, cfg)
        ns = {**feats.as_namespace(), "th": cfg.thresholds}
        out: list[Finding] = []
        for pattern in catalog.declarative():
            # Mined candidates are correlational until promoted — opt-in only.
            if pattern.maturity == "candidate" and not cfg.match_candidate_patterns:
                continue
            code = pattern.compiled()
            if code is None or not evaluate(code, ns):
                continue
            fdict = feats.to_dict()
            evidence = {s: fdict[s] for s in pattern.signals if s in fdict}
            evidence["maturity"] = pattern.maturity
            if pattern.remediation_skill:
                evidence["remediation_skill"] = pattern.remediation_skill
            out.append(Finding(
                detector_id=f"taxonomy.{pattern.id}",
                analysis_no=pattern.analysis_no,
                severity=_SEV.get(pattern.severity, Severity.INFO),
                title=pattern.title,
                evidence=evidence,
                recommendation=pattern.recommendation,
                pattern_id=pattern.id,
                deep_enrichable=pattern.severity in ("med", "high"),
            ))
        return out


DETECTOR = TaxonomyMatchDetector()
