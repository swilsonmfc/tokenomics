"""Taxonomy matcher — evaluates declarative catalog patterns against features.

This is the "pattern match against a taxonomy" engine: it computes the shared
trajectory feature vector once, then fires every declarative pattern whose rule
holds. Detector-backed patterns are handled by their own modules (which stamp
``Finding.pattern_id``); this detector only emits the declarative ones, so adding
a new declarative pattern is a catalog edit, not a code change.
"""

from __future__ import annotations

from ..config import Config
from ..features import compute_features, compute_session_features
from ..model import Corpus
from ..taxonomy.evaluator import evaluate
from .base import Finding, Severity

_SEV = {"info": Severity.INFO, "low": Severity.LOW, "med": Severity.MED, "high": Severity.HIGH}


class TaxonomyMatchDetector:
    id = "taxonomy_match"
    title = "Taxonomy pattern match"
    analysis_no = 0  # per-finding analysis_no comes from the pattern's category

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        catalog = corpus.catalog  # loaded at assembly — detector stays pure (no I/O)
        feats = compute_features(corpus, cfg)
        fdict = feats.to_dict()
        corpus_ns = {**feats.as_namespace(), "th": cfg.thresholds}
        # Mined thresholds were fit on the per-session distribution, so a
        # session-scoped rule is judged the same way: how many sessions it holds
        # in, not whether it holds on the all-sessions-folded vector (where summed
        # int signals balloon and the rule would near-always fire). Built lazily.
        session_ns: list[dict] | None = None
        out: list[Finding] = []
        for pattern in catalog.declarative():
            # Mined candidates are correlational until promoted — opt-in only.
            if pattern.maturity == "candidate" and not cfg.match_candidate_patterns:
                continue
            code = pattern.compiled()
            if code is None:
                continue
            extra: dict = {}
            if pattern.scope == "session":
                if session_ns is None:
                    session_ns = [
                        {**compute_session_features(s, corpus.static, cfg).as_namespace(),
                         "th": cfg.thresholds}
                        for s in corpus.sessions
                    ]
                if not session_ns:
                    continue
                hits = sum(1 for ns in session_ns if evaluate(code, ns))
                ratio = hits / len(session_ns)
                if ratio < cfg.thresholds.mine_session_hit_ratio:
                    continue
                extra = {"session_hit_ratio": round(ratio, 3),
                         "sessions_matched": hits, "sessions_total": len(session_ns)}
            elif not evaluate(code, corpus_ns):
                continue

            evidence = {s: fdict[s] for s in pattern.signals if s in fdict}
            evidence["maturity"] = pattern.maturity
            evidence.update(extra)
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
