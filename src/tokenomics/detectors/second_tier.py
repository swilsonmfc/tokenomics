"""D7 — Second-tier savings: a bundle of pluggable sub-checks, one Finding each.

Sub-checks: redundant file re-reads, tool_result bloat, oversized/tiny subagent
fan-out, server-tool (web search/fetch) waste, thinking-on-trivial.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .. import pricing
from ..config import Config
from ..model import Corpus
from ._util import all_turns
from .base import Confidence, Finding, Severity


def _dominant_model(corpus: Corpus) -> str | None:
    """Model carrying the most tokens — used to price corpus-wide savings."""
    mt: Counter[str] = Counter()
    for turn, default_model, _ in all_turns(corpus):
        if turn.usage and turn.usage.total_tokens:
            mt[pricing.normalize_model(turn.model or default_model) or "unknown"] += \
                turn.usage.total_tokens
    return mt.most_common(1)[0][0] if mt else None


def _rereads(corpus: Corpus, cfg: Config) -> Finding | None:
    th = cfg.thresholds
    reads: Counter[str] = Counter()
    edited: set[str] = set()
    chars: dict[str, int] = defaultdict(int)
    for turn, _, _ in all_turns(corpus):
        for call in turn.tool_calls:
            fp = call.input.get("file_path")
            if call.name == "Read" and fp:
                reads[fp] += 1
                if call.result_chars:
                    chars[fp] += call.result_chars
            elif call.name in ("Edit", "Write", "MultiEdit") and fp:
                edited.add(fp)
    offenders = {fp: c for fp, c in reads.items() if c >= th.reread and fp not in edited}
    if not offenders:
        return None
    # Avoidable = every read past the first: (reads-1)/reads of the file's read volume.
    avoidable = sum(int((chars[fp] // 4) * (c - 1) / c) for fp, c in offenders.items())
    savings = pricing.estimate_savings(
        avoidable, _dominant_model(corpus), kind="input",
        frac=th.reread_avoidable_frac, confidence=Confidence.MED)
    return Finding(
        detector_id="second_tier.rereads", analysis_no=7, severity=Severity.LOW,
        title=f"{len(offenders)} file(s) re-read ≥{th.reread}× without edits",
        evidence={"files": dict(sorted(offenders.items(), key=lambda kv: -kv[1])[:8])},
        recommendation="Re-reading an unchanged file re-pays its tokens. Read once and "
                       "reuse, or narrow with offset/limit.",
        pattern_id="secondtier.file-reread",
        **savings,
    )


def _tool_bloat(corpus: Corpus, cfg: Config) -> Finding | None:
    th = cfg.thresholds
    big = []
    for turn, _, session in all_turns(corpus):
        for call in turn.tool_calls:
            if call.result_chars and call.result_chars >= th.tool_result_bloat_chars:
                big.append({"tool": call.name, "chars": call.result_chars,
                            "session": session.session_id})
    if not big:
        return None
    big.sort(key=lambda b: -b["chars"])
    # Only a fraction of large output is truly unnecessary — most is requested.
    bloat_tokens = sum(b["chars"] for b in big) // 4
    savings = pricing.estimate_savings(
        bloat_tokens, _dominant_model(corpus), kind="input",
        frac=th.tool_bloat_avoidable_frac, confidence=Confidence.LOW)
    return Finding(
        detector_id="second_tier.tool_bloat", analysis_no=7, severity=Severity.LOW,
        title=f"{len(big)} oversized tool result(s) (≥{th.tool_result_bloat_chars:,} chars)",
        evidence={"top": big[:8]},
        recommendation="Large tool outputs re-enter context on every following turn. "
                       "Narrow reads (head/limit/grep), or summarize before feeding back.",
        pattern_id="secondtier.toolresult-bloat",
        **savings,
    )


def _fanout(corpus: Corpus, cfg: Config) -> Finding | None:
    th = cfg.thresholds
    per_turn: Counter[str] = Counter()
    for session in corpus.sessions:
        for turn in session.turns:
            spawns = sum(1 for c in turn.tool_calls if c.spawned_subagent)
            if spawns:
                per_turn[turn.uuid] = spawns
    big = {u: n for u, n in per_turn.items() if n > th.fanout}
    if not big:
        return None
    # Each agent past the fanout budget re-pays a fixed prompt/tool overhead.
    excess_agents = sum(n - th.fanout for n in big.values())
    savings = pricing.estimate_savings(
        excess_agents * th.fanout_overhead_tokens, _dominant_model(corpus),
        kind="input", confidence=Confidence.LOW)
    return Finding(
        detector_id="second_tier.fanout", analysis_no=7, severity=Severity.LOW,
        title=f"{len(big)} turn(s) fanned out >{th.fanout} subagents at once",
        evidence={"turns": dict(list(big.items())[:8]), "excess_agents": excess_agents},
        recommendation="Very wide subagent fan-out multiplies fixed per-agent overhead. "
                       "Batch work or reduce parallelism where agents aren't independent.",
        pattern_id="secondtier.wide-fanout",
        **savings,
    )


def _server_tools(corpus: Corpus, cfg: Config) -> Finding | None:
    searches = fetches = 0
    for turn, _, _ in all_turns(corpus):
        if turn.usage:
            searches += turn.usage.web_search_requests
            fetches += turn.usage.web_fetch_requests
    if searches + fetches < cfg.thresholds.server_tool_min_calls:
        return None
    return Finding(
        detector_id="second_tier.server_tools", analysis_no=7, severity=Severity.INFO,
        title=f"{searches} web searches + {fetches} web fetches",
        evidence={"web_search_requests": searches, "web_fetch_requests": fetches},
        recommendation="Heavy server-tool use adds billed requests and context. Confirm "
                       "each search/fetch is needed; cache results where repeated.",
        pattern_id="secondtier.server-tool-waste",
    )


SUBCHECKS = [_rereads, _tool_bloat, _fanout, _server_tools]


class SecondTierDetector:
    id = "second_tier"
    title = "Second-tier savings"
    analysis_no = 7

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        out = []
        for check in SUBCHECKS:
            f = check(corpus, cfg)
            if f is not None:
                out.append(f)
        return out


DETECTOR = SecondTierDetector()
