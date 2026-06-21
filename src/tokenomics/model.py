"""Internal data model assembled from raw Claude Code session JSONL.

Every detector consumes these dataclasses, never raw records. Keeping the model
small and explicit is what lets the parser stay schema-tolerant (it can map two
log generations onto one shape) while detectors stay simple.

Token-accounting rules baked into this model:
  * ``TokenUsage`` is populated ONLY from a record's top-level ``message.usage``.
    Never from ``usage.iterations[]`` (those repeat the same counts per
    streaming iteration and would double-count).
  * Subagent tokens are counted ONCE, from the subagent transcript's own turns.
    ``SubagentRun.rollup_*`` (from the parent ``toolUseResult``) is kept only for
    cross-checking, never added on top of the transcript turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .taxonomy import Catalog


@dataclass(frozen=True)
class TokenUsage:
    """Top-level ``message.usage`` for one assistant turn."""

    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    ephemeral_1h: int = 0
    ephemeral_5m: int = 0
    web_search_requests: int = 0
    web_fetch_requests: int = 0

    @property
    def fresh_input(self) -> int:
        """Uncached prompt tokens billed at full rate (fresh + cache writes)."""
        return self.input + self.cache_creation

    @property
    def cached_input(self) -> int:
        return self.cache_read

    @property
    def total_tokens(self) -> int:
        return self.input + self.output + self.cache_creation + self.cache_read

    @property
    def context_size(self) -> int:
        """Prompt size presented to the model this turn (a context-window proxy)."""
        return self.input + self.cache_read + self.cache_creation

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_creation=self.cache_creation + other.cache_creation,
            cache_read=self.cache_read + other.cache_read,
            ephemeral_1h=self.ephemeral_1h + other.ephemeral_1h,
            ephemeral_5m=self.ephemeral_5m + other.ephemeral_5m,
            web_search_requests=self.web_search_requests + other.web_search_requests,
            web_fetch_requests=self.web_fetch_requests + other.web_fetch_requests,
        )

    @classmethod
    def zero(cls) -> TokenUsage:
        return cls()


@dataclass(frozen=True)
class ToolCall:
    """A single ``tool_use`` block plus a pointer to its result."""

    id: str
    name: str
    is_mcp: bool = False
    mcp_server: str | None = None
    caller_type: str = "direct"
    input: dict = field(default_factory=dict)
    result_tool_use_id: str | None = None
    result_chars: int | None = None
    spawned_subagent: str | None = None  # agentId when name in {Agent, Task}
    ts: datetime | None = None
    turn_uuid: str | None = None


@dataclass
class Turn:
    """One ``assistant`` or ``user`` record on the conversation DAG."""

    uuid: str
    parent_uuid: str | None
    ts: datetime | None
    role: str  # "assistant" | "user" | "system"
    model: str | None = None
    usage: TokenUsage | None = None
    thinking_chars: int = 0
    text_chars: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_tool_result: bool = False
    is_sidechain: bool = False
    attribution_plugin: str | None = None
    attribution_skill: str | None = None
    request_id: str | None = None
    skipped_for_usage: bool = False  # isCompactSummary / isApiErrorMessage


@dataclass
class SubagentRun:
    """A spawned subagent: its rollup (from the parent) + its own transcript."""

    agent_id: str
    agent_type: str | None
    description: str | None
    parent_tool_use_id: str | None
    parent_turn_uuid: str | None = None
    resolved_model: str | None = None
    rollup_total_tokens: int = 0
    rollup_usage: TokenUsage | None = None
    tool_stats: dict = field(default_factory=dict)
    total_tool_use_count: int = 0
    duration_ms: int = 0
    turns: list[Turn] = field(default_factory=list)

    @property
    def model(self) -> str | None:
        """Best-effort model: resolved rollup, else first transcript model."""
        if self.resolved_model:
            return self.resolved_model
        for t in self.turns:
            if t.model:
                return t.model
        return None


@dataclass
class Session:
    """One top-level session file plus its linked subagent transcripts."""

    session_id: str
    project_path: str
    file_path: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    cc_version: str | None = None
    git_branch: str | None = None
    entrypoint: str | None = None
    turns: list[Turn] = field(default_factory=list)  # main thread only
    subagents: list[SubagentRun] = field(default_factory=list)

    @property
    def models_used(self) -> set[str]:
        models = {t.model for t in self.turns if t.model}
        for sub in self.subagents:
            if sub.model:
                models.add(sub.model)
        return models


@dataclass
class StaticEnv:
    """Static "harness shape": installed plugins, skills, agents, hooks, MCP, CLAUDE.md.

    Populated by ``static_analysis``. Left as plain dicts/lists so detectors can
    read opportunistically without a rigid schema across config generations.
    """

    plugins: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
    claude_md: list[dict] = field(default_factory=list)


@dataclass
class Corpus:
    """All analyzed sessions for one project plus the static environment."""

    project_path: str
    sessions: list[Session] = field(default_factory=list)
    static: StaticEnv = field(default_factory=StaticEnv)
    cc_versions: set[str] = field(default_factory=set)
    file_count: int = 0
    byte_size: int = 0
    # Best-practice catalog (curated + this project's mined/promoted patterns),
    # loaded once at assembly so detectors stay pure (no I/O in ``run``).
    catalog: Catalog = field(default_factory=Catalog)
