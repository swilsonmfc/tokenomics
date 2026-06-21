"""D1 — Code-context search efficiency: grep-heavy trajectories, no indexer."""

from __future__ import annotations

from collections import Counter

from .. import pricing
from ..config import Config
from ..model import Corpus
from ._util import all_turns, is_search_call
from .base import Confidence, Finding, Severity


def _indexer_installed(corpus: Corpus) -> str | None:
    for p in corpus.static.plugins:
        name = (p.get("name") or "").lower()
        if "lsp" in name or "pyright" in name or "ast" in name or "index" in name:
            return p.get("name")
    return None


class SearchEfficiencyDetector:
    id = "search_efficiency"
    title = "Code-context search efficiency"
    analysis_no = 1

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        total_calls = 0
        search_calls = 0
        grep_patterns: Counter[str] = Counter()
        pattern_tokens: Counter[str] = Counter()
        model_tokens: Counter[str] = Counter()

        for turn, default_model, _ in all_turns(corpus):
            if turn.usage and turn.usage.total_tokens:
                model_tokens[pricing.normalize_model(turn.model or default_model)
                             or "unknown"] += turn.usage.total_tokens
            for call in turn.tool_calls:
                total_calls += 1
                if is_search_call(call):
                    search_calls += 1
                    pat = str(call.input.get("pattern")
                              or call.input.get("command") or "").strip()[:120]
                    if pat:
                        grep_patterns[pat] += 1
                        if call.result_chars:
                            pattern_tokens[pat] += call.result_chars // 4

        if total_calls == 0:
            return []

        findings: list[Finding] = []
        ratio = search_calls / total_calls
        indexer = _indexer_installed(corpus)
        repeated = [(p, c) for p, c in grep_patterns.most_common(5) if c >= th.repeat_grep]
        dominant_model = model_tokens.most_common(1)[0][0] if model_tokens else None
        # Avoidable = result tokens of *repeated* identical searches (an index
        # removes the re-scan). If an indexer is already installed, the realizable
        # saving is ~0 — flag the behavior but don't claim tokens back.
        repeated_tokens = sum(pattern_tokens[p] for p, c in grep_patterns.items()
                              if c >= th.repeat_grep)

        search_heavy = ratio >= th.search_ratio and search_calls >= th.search_min_calls
        if search_heavy:
            sev = Severity.HIGH if not indexer else Severity.MED
            savings = pricing.estimate_savings(
                0 if indexer else repeated_tokens, dominant_model,
                kind="input", frac=th.search_avoidable_frac, confidence=Confidence.LOW)
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                title=(f"Search-heavy: {search_calls}/{total_calls} tool calls "
                       f"({ratio:.0%}) are text search"),
                evidence={
                    "search_calls": search_calls,
                    "total_calls": total_calls,
                    "ratio": round(ratio, 3),
                    "indexer_installed": indexer,
                    "repeated_search_tokens": repeated_tokens,
                    "top_patterns": grep_patterns.most_common(5),
                },
                recommendation=(
                    (f"An indexing tool ({indexer}) is installed but the trajectory "
                     "leans on raw grep — prefer LSP navigation/symbol lookup. ")
                    if indexer else
                    "No code-indexing tool detected. Adding LSP/AST/RepoMap navigation "
                    "cuts repeated full-text scans. See the code-indexing-advisor skill."
                ),
                pattern_id="search.grep-heavy",
                deep_enrichable=True,
                **savings,
            ))
        if repeated and not search_heavy:
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=Severity.LOW,
                title=f"{len(repeated)} search pattern(s) repeated ≥{th.repeat_grep}×",
                evidence={"repeated_patterns": repeated},
                recommendation="Cache or narrow these repeated searches; an index avoids "
                               "re-scanning the same files.",
                pattern_id="search.grep-heavy",
            ))
        return findings


DETECTOR = SearchEfficiencyDetector()
