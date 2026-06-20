"""Deterministic rollups over the assembled Corpus.

All token sums obey the accounting invariant: subagent tokens are counted from
their transcripts, never from the parent rollup (which is used only by
``reconcile_subagents`` to cross-check that we aren't double-counting).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import pricing
from .model import Corpus, Session, SubagentRun, TokenUsage, Turn


def _sum_usage(turns: list[Turn]) -> TokenUsage:
    total = TokenUsage.zero()
    for t in turns:
        if t.usage is not None:
            total = total + t.usage
    return total


def session_main_usage(session: Session) -> TokenUsage:
    return _sum_usage(session.turns)


def subagent_usage(sub: SubagentRun) -> TokenUsage:
    # Counted from the transcript turns (the authoritative billing source: each
    # turn re-reads the cache and is billed for it).
    return _sum_usage(sub.turns)


def _last_turn_usage(turns: list[Turn]) -> TokenUsage:
    for turn in reversed(turns):
        if turn.usage is not None:
            return turn.usage
    return TokenUsage.zero()


def session_total_usage(session: Session) -> TokenUsage:
    total = session_main_usage(session)
    for sub in session.subagents:
        total = total + subagent_usage(sub)
    return total


@dataclass
class Reconciliation:
    agent_id: str
    last_turn_tokens: int   # final transcript turn (matches rollup snapshot)
    rollup_tokens: int
    transcript_total: int   # full billed sum across turns (informational)

    @property
    def delta(self) -> int:
        return self.last_turn_tokens - self.rollup_tokens

    @property
    def within_tolerance(self) -> bool:
        # The parent rollup's totalTokens is the subagent's FINAL-turn usage
        # total, not a sum. Linkage is correct when our parsed final turn
        # matches it; the full transcript sum is legitimately larger.
        if self.rollup_tokens == 0:
            return True  # no rollup to check against
        return abs(self.delta) <= max(100, int(self.rollup_tokens * 0.05))


def reconcile_subagents(corpus: Corpus) -> list[Reconciliation]:
    """Cross-check the subagent's final-turn usage vs parent rollup totalTokens."""
    out: list[Reconciliation] = []
    for session in corpus.sessions:
        for sub in session.subagents:
            last = _last_turn_usage(sub.turns).total_tokens
            full = subagent_usage(sub).total_tokens
            out.append(Reconciliation(sub.agent_id, last, sub.rollup_total_tokens, full))
    return out


@dataclass
class CorpusMetrics:
    total_usage: TokenUsage
    total_cost_usd: float
    total_weight: float
    by_model_tokens: dict[str, int] = field(default_factory=dict)
    by_model_cost: dict[str, float] = field(default_factory=dict)
    by_plugin_tokens: dict[str, int] = field(default_factory=dict)
    by_skill_tokens: dict[str, int] = field(default_factory=dict)
    tool_histogram: dict[str, int] = field(default_factory=dict)
    mcp_servers_used: dict[str, int] = field(default_factory=dict)
    cache_read: int = 0
    cache_creation: int = 0
    session_count: int = 0
    subagent_count: int = 0
    unpriced_models: list[str] = field(default_factory=list)

    @property
    def cache_efficiency(self) -> float:
        denom = self.cache_read + self.cache_creation
        return self.cache_read / denom if denom else 1.0


def compute_metrics(corpus: Corpus) -> CorpusMetrics:
    total = TokenUsage.zero()
    cost = 0.0
    weight = 0.0
    by_model_tokens: Counter[str] = Counter()
    by_model_cost: dict[str, float] = defaultdict(float)
    by_plugin: Counter[str] = Counter()
    by_skill: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    mcp: Counter[str] = Counter()
    unpriced: set[str] = set()

    def account(turn: Turn, default_model: str | None) -> None:
        nonlocal total, cost, weight
        if turn.usage is None or turn.usage.total_tokens == 0:
            return
        model = turn.model or default_model
        total = total + turn.usage
        c = pricing.usage_cost_usd(turn.usage, model)
        if c is None:
            if model:
                unpriced.add(pricing.normalize_model(model) or model)
        else:
            cost += c
            by_model_cost[pricing.normalize_model(model) or "unknown"] += c
        weight += pricing.usage_weight(turn.usage, model)
        by_model_tokens[pricing.normalize_model(model) or "unknown"] += turn.usage.total_tokens
        if turn.attribution_plugin:
            by_plugin[turn.attribution_plugin] += turn.usage.total_tokens
        if turn.attribution_skill:
            by_skill[turn.attribution_skill] += turn.usage.total_tokens

    def count_tools(turn: Turn) -> None:
        for call in turn.tool_calls:
            tools[call.name] += 1
            if call.is_mcp and call.mcp_server:
                mcp[call.mcp_server] += 1

    subagent_count = 0
    for session in corpus.sessions:
        for turn in session.turns:
            account(turn, None)
            count_tools(turn)
        for sub in session.subagents:
            subagent_count += 1
            for turn in sub.turns:
                account(turn, sub.model)
                count_tools(turn)

    return CorpusMetrics(
        total_usage=total,
        total_cost_usd=cost,
        total_weight=weight,
        by_model_tokens=dict(by_model_tokens.most_common()),
        by_model_cost=dict(sorted(by_model_cost.items(), key=lambda kv: -kv[1])),
        by_plugin_tokens=dict(by_plugin.most_common()),
        by_skill_tokens=dict(by_skill.most_common()),
        tool_histogram=dict(tools.most_common()),
        mcp_servers_used=dict(mcp.most_common()),
        cache_read=total.cache_read,
        cache_creation=total.cache_creation,
        session_count=len(corpus.sessions),
        subagent_count=subagent_count,
        unpriced_models=sorted(unpriced),
    )


def context_series(session: Session) -> list[int]:
    """Per-assistant-turn context size proxy (input + cache_read + cache_creation)."""
    return [t.usage.context_size for t in session.turns if t.usage is not None]


def session_context_peak_avg(session: Session) -> tuple[int, float]:
    series = context_series(session)
    if not series:
        return 0, 0.0
    return max(series), sum(series) / len(series)
