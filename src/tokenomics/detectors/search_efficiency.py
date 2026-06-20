"""D1 — Code-context search efficiency: grep-heavy trajectories, no indexer."""

from __future__ import annotations

from collections import Counter

from ..config import Config
from ..model import Corpus
from ._util import all_turns, is_search_call
from .base import Finding, Severity


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
        search_tokens = 0
        grep_patterns: Counter[str] = Counter()

        for turn, _, _ in all_turns(corpus):
            for call in turn.tool_calls:
                total_calls += 1
                if is_search_call(call):
                    search_calls += 1
                    if call.result_chars:
                        search_tokens += call.result_chars // 4
                    pat = call.input.get("pattern") or call.input.get("command") or ""
                    if pat:
                        grep_patterns[str(pat).strip()[:120]] += 1

        if total_calls == 0:
            return []

        findings: list[Finding] = []
        ratio = search_calls / total_calls
        indexer = _indexer_installed(corpus)
        repeated = [(p, c) for p, c in grep_patterns.most_common(5) if c >= th.repeat_grep]

        search_heavy = ratio >= th.search_ratio and search_calls >= th.search_min_calls
        if search_heavy:
            sev = Severity.HIGH if not indexer else Severity.MED
            est = int(search_tokens * th.search_reduction_factor)
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                title=(f"Search-heavy: {search_calls}/{total_calls} tool calls "
                       f"({ratio:.0%}) are text search"),
                evidence={
                    "search_calls": search_calls,
                    "total_calls": total_calls,
                    "ratio": round(ratio, 3),
                    "indexer_installed": indexer,
                    "top_patterns": grep_patterns.most_common(5),
                },
                est_savings_tokens=est,
                est_savings_weight=est / 1_000_000 * 5,
                recommendation=(
                    (f"An indexing tool ({indexer}) is installed but the trajectory "
                     "leans on raw grep — prefer LSP navigation/symbol lookup. ")
                    if indexer else
                    "No code-indexing tool detected. Adding LSP/AST/RepoMap navigation "
                    "cuts repeated full-text scans. See the code-indexing-advisor skill."
                ),
                pattern_id="search.grep-heavy",
                deep_enrichable=True,
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
