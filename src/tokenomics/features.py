"""Trajectory feature layer — one normalized signal vector per corpus.

This is the substrate the taxonomy matches against. Today each detector
recomputes its own signals; this module computes them once into a flat,
serializable ``TrajectoryFeatures`` so that (a) declarative taxonomy patterns can
be evaluated against a stable namespace and (b) the same vector can later be
clustered for empirical (corpus-mined) pattern discovery and cross-project
benchmarking.

Kept self-contained (no ``detectors`` imports) to avoid an import cycle with the
detector that consumes it. Pure: no I/O.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from . import pricing
from .config import MODEL_TIER, Config
from .metrics import session_context_peak_avg
from .model import Corpus, ToolCall

# Canonical search-call detection (re-exported by detectors/_util; defined here
# because features can't import the detectors package without a cycle).
SEARCH_TOOLS = {"Grep", "Glob"}
SEARCH_BASH = ("grep", "rg ", "ripgrep", "find ", "ag ", "ack ")
_PREMIUM_TIER = 3


def is_search_call(call: ToolCall) -> bool:
    if call.name in SEARCH_TOOLS:
        return True
    if call.name == "Bash":
        cmd = str(call.input.get("command", "")).lower()
        return any(tok in cmd for tok in SEARCH_BASH)
    return False


@dataclass(frozen=True)
class TrajectoryFeatures:
    """Flat, declarative-rule-friendly signal vector for one corpus."""

    total_turns: int = 0
    total_tool_calls: int = 0
    search_calls: int = 0
    search_ratio: float = 0.0
    repeated_search_max: int = 0
    total_tokens: int = 0
    output_tokens: int = 0
    weight: float = 0.0
    premium_token_share: float = 0.0
    top_model: str | None = None
    trivial_premium_turns: int = 0
    trivial_premium_ratio: float = 0.0
    thinking_trivial_turns: int = 0
    cache_efficiency: float = 1.0
    bust_turns: int = 0
    ctx_peak: int = 0
    ctx_avg: float = 0.0
    reread_files: int = 0
    max_fanout: int = 0
    web_requests: int = 0
    claudemd_tokens: int = 0
    unused_mcp_count: int = 0
    subagent_count: int = 0
    premium_subagent_runs: int = 0
    agent_count: int = 0
    cheap_pinned_agents: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def as_namespace(self) -> dict:
        """Variables exposed to declarative pattern rules."""
        return asdict(self)


def compute_features(corpus: Corpus, cfg: Config) -> TrajectoryFeatures:
    """Corpus-level feature vector (all sessions folded together)."""
    return _compute(corpus.sessions, corpus.static, cfg)


def compute_session_features(session, static, cfg: Config) -> TrajectoryFeatures:
    """Per-session feature vector — the unit the empirical miner contrasts."""
    return _compute([session], static, cfg)


def _compute(sessions, static, cfg: Config) -> TrajectoryFeatures:
    th = cfg.thresholds
    total_turns = total_calls = search_calls = 0
    tokens_by_model: Counter[str] = Counter()
    trivial_premium = thinking_trivial = 0
    cache_read = cache_create = bust_turns = 0
    output_tokens = 0
    weight = 0.0
    search_patterns: Counter[str] = Counter()
    reads: Counter[str] = Counter()
    edited: set[str] = set()
    max_fanout = web_requests = 0

    def visit(turn, default_model):
        nonlocal total_turns, total_calls, search_calls, trivial_premium
        nonlocal thinking_trivial, cache_read, cache_create, bust_turns, web_requests
        nonlocal output_tokens, weight
        u = turn.usage
        if u is None or u.total_tokens == 0:
            return
        total_turns += 1
        model = pricing.normalize_model(turn.model or default_model) or "unknown"
        tokens_by_model[model] += u.total_tokens
        output_tokens += u.output
        weight += pricing.usage_weight(u, turn.model or default_model)
        tier = MODEL_TIER.get(model, 0)
        is_premium = tier >= _PREMIUM_TIER
        is_trivial = u.output < th.trivial_output_tokens and not turn.tool_calls
        if is_premium and is_trivial and turn.thinking_chars == 0:
            trivial_premium += 1
        if is_premium and is_trivial and turn.thinking_chars > 0:
            thinking_trivial += 1
        cache_read += u.cache_read
        cache_create += u.cache_creation
        if (u.cache_creation > th.cache_bust_min_creation
                and u.cache_read < u.cache_creation * th.cache_bust_read_ratio):
            bust_turns += 1
        web_requests += u.web_search_requests + u.web_fetch_requests
        for call in turn.tool_calls:
            total_calls += 1
            if is_search_call(call):
                search_calls += 1
                pat = call.input.get("pattern") or call.input.get("command") or ""
                if pat:
                    search_patterns[str(pat).strip()[:120]] += 1
            fp = call.input.get("file_path")
            if call.name == "Read" and fp:
                reads[fp] += 1
            elif call.name in ("Edit", "Write", "MultiEdit") and fp:
                edited.add(fp)

    subagent_count = premium_subagent_runs = 0
    for session in sessions:
        for turn in session.turns:
            visit(turn, None)
            spawns = sum(1 for c in turn.tool_calls if c.spawned_subagent)
            max_fanout = max(max_fanout, spawns)
        for sub in session.subagents:
            subagent_count += 1
            sub_model = pricing.normalize_model(sub.model)
            if sub_model and MODEL_TIER.get(sub_model, 0) >= _PREMIUM_TIER:
                premium_subagent_runs += 1
            for turn in sub.turns:
                visit(turn, sub.model)

    total_tokens = sum(tokens_by_model.values())
    top_model, top_tokens = (tokens_by_model.most_common(1)[0]
                             if tokens_by_model else (None, 0))
    premium_share = (
        sum(t for m, t in tokens_by_model.items() if MODEL_TIER.get(m, 0) >= _PREMIUM_TIER)
        / total_tokens
    ) if total_tokens else 0.0

    denom = cache_read + cache_create
    cache_eff = cache_read / denom if denom else 1.0

    peaks = [session_context_peak_avg(s) for s in sessions]
    peaks = [(p, a) for p, a in peaks if p]
    ctx_peak = max((p for p, _ in peaks), default=0)
    ctx_avg = (sum(a for _, a in peaks) / len(peaks)) if peaks else 0.0

    reread_files = sum(1 for fp, c in reads.items() if c >= th.reread and fp not in edited)

    used_servers = {
        c.mcp_server
        for s in sessions for t in s.turns for c in t.tool_calls
        if c.is_mcp and c.mcp_server
    }
    static_servers = {s.get("name") for s in static.mcp_servers if s.get("name")}
    unused_mcp = len(static_servers - used_servers)
    def _is_cheap_pin(agent: dict) -> bool:
        m = pricing.normalize_model(agent.get("model"))
        return bool(m) and MODEL_TIER.get(m or "", 9) < _PREMIUM_TIER

    cheap_pinned = sum(1 for a in static.agents if _is_cheap_pin(a))
    claudemd_tokens = max((d.get("est_tokens", 0) for d in static.claude_md), default=0)

    return TrajectoryFeatures(
        total_turns=total_turns,
        total_tool_calls=total_calls,
        search_calls=search_calls,
        search_ratio=round(search_calls / total_calls, 4) if total_calls else 0.0,
        repeated_search_max=max(search_patterns.values(), default=0),
        total_tokens=total_tokens,
        output_tokens=output_tokens,
        weight=round(weight, 4),
        premium_token_share=round(premium_share, 4),
        top_model=top_model,
        trivial_premium_turns=trivial_premium,
        trivial_premium_ratio=round(trivial_premium / total_turns, 4) if total_turns else 0.0,
        thinking_trivial_turns=thinking_trivial,
        cache_efficiency=round(cache_eff, 4),
        bust_turns=bust_turns,
        ctx_peak=ctx_peak,
        ctx_avg=round(ctx_avg, 1),
        reread_files=reread_files,
        max_fanout=max_fanout,
        web_requests=web_requests,
        claudemd_tokens=claudemd_tokens,
        unused_mcp_count=unused_mcp,
        subagent_count=subagent_count,
        premium_subagent_runs=premium_subagent_runs,
        agent_count=len(static.agents),
        cheap_pinned_agents=cheap_pinned,
    )
