"""Fold raw JSONL records into the ``model`` dataclasses.

Token-accounting invariant (the central correctness risk):
  * A turn's ``TokenUsage`` comes ONLY from top-level ``message.usage`` — never
    ``usage.iterations[]`` (duplicative per streaming iteration).
  * Subagent tokens are counted ONCE, from the subagent transcript's own turns.
    The parent ``toolUseResult`` rollup is parsed for cross-checking only.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .logparse import iter_records, load_meta
from .logpath import (
    SessionFiles,
    all_project_log_dirs,
    corpus_byte_size,
    denamespace,
    discover_sessions,
    discover_sessions_in_dir,
)
from .model import (
    Corpus,
    Session,
    StaticEnv,
    SubagentRun,
    TokenUsage,
    ToolCall,
    Turn,
)

# Record types that are not conversation turns — skipped by the assembler.
_NON_TURN_TYPES = {
    "file-history-snapshot", "mode", "permission-mode", "last-prompt",
    "ai-title", "agent-name", "bridge-session", "queue-operation",
}
_SUBAGENT_SPAWN_TOOLS = {"Agent", "Task"}


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_usage(usage: dict | None) -> TokenUsage | None:
    if not isinstance(usage, dict):
        return None
    cache_creation = usage.get("cache_creation") or {}
    server = usage.get("server_tool_use") or {}
    return TokenUsage(
        input=int(usage.get("input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
        cache_creation=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read=int(usage.get("cache_read_input_tokens") or 0),
        ephemeral_1h=int(cache_creation.get("ephemeral_1h_input_tokens") or 0),
        ephemeral_5m=int(cache_creation.get("ephemeral_5m_input_tokens") or 0),
        web_search_requests=int(server.get("web_search_requests") or 0),
        web_fetch_requests=int(server.get("web_fetch_requests") or 0),
    )


def _content_blocks(message: dict) -> list:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _result_chars(content) -> int | None:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for blk in content:
            if isinstance(blk, dict):
                t = blk.get("text")
                if isinstance(t, str):
                    total += len(t)
                elif isinstance(blk.get("content"), str):
                    total += len(blk["content"])
        return total
    return None


def _build_turn(rec: dict) -> Turn | None:
    rtype = rec.get("type")
    if rtype not in ("assistant", "user", "system"):
        return None
    message = rec.get("message")
    if not isinstance(message, dict):
        message = {}

    skipped = bool(rec.get("isCompactSummary") or rec.get("isApiErrorMessage"))
    usage = None if skipped else _parse_usage(message.get("usage"))

    thinking_chars = 0
    text_chars = 0
    tool_calls: list[ToolCall] = []
    is_tool_result = False
    ts = _parse_ts(rec.get("timestamp"))
    uuid = rec.get("uuid") or ""

    for blk in _content_blocks(message):
        if not isinstance(blk, dict):
            continue
        bt = blk.get("type")
        if bt == "thinking":
            thinking_chars += len(blk.get("thinking") or "")
        elif bt == "text":
            text_chars += len(blk.get("text") or "")
        elif bt == "tool_use":
            name = blk.get("name") or ""
            is_mcp = name.startswith("mcp__")
            mcp_server = name.split("__")[1] if is_mcp and name.count("__") >= 2 else None
            caller = blk.get("caller") or {}
            tool_calls.append(ToolCall(
                id=blk.get("id") or "",
                name=name,
                is_mcp=is_mcp,
                mcp_server=mcp_server,
                caller_type=caller.get("type") or "direct",
                input=blk.get("input") if isinstance(blk.get("input"), dict) else {},
                ts=ts,
                turn_uuid=uuid,
                spawned_subagent=None,  # filled from toolUseResult below
            ))
        elif bt == "tool_result":
            is_tool_result = True

    return Turn(
        uuid=uuid,
        parent_uuid=rec.get("parentUuid"),
        ts=ts,
        role=rtype,
        model=message.get("model"),
        usage=usage,
        thinking_chars=thinking_chars,
        text_chars=text_chars,
        tool_calls=tool_calls,
        is_tool_result=is_tool_result,
        is_sidechain=bool(rec.get("isSidechain")),
        attribution_plugin=rec.get("attributionPlugin"),
        attribution_skill=rec.get("attributionSkill"),
        request_id=rec.get("requestId"),
        skipped_for_usage=skipped,
    )


def _link_tool_results(turns: list[Turn], raw_by_uuid: dict[str, dict]) -> None:
    """Attach result sizes + subagent spawn ids to the originating ToolCall."""
    # Index tool_result blocks (in user records) by tool_use_id, and the rich
    # toolUseResult aggregates by their tool_use_id too.
    result_chars: dict[str, int] = {}
    agent_ids: dict[str, str] = {}  # tool_use_id -> agentId
    for rec in raw_by_uuid.values():
        if rec.get("type") != "user":
            continue
        message = rec.get("message") or {}
        for blk in _content_blocks(message) if isinstance(message, dict) else []:
            if isinstance(blk, dict) and blk.get("type") == "tool_result":
                tuid = blk.get("tool_use_id")
                if tuid:
                    rc = _result_chars(blk.get("content"))
                    if rc is not None:
                        result_chars[tuid] = rc
        tur = rec.get("toolUseResult")
        if isinstance(tur, dict):
            # tool_use_id lives on the matching tool_result; agentId on the rollup
            agent_id = tur.get("agentId")
            tuid = _find_tool_result_id(message)
            if agent_id and tuid:
                agent_ids[tuid] = agent_id

    for turn in turns:
        for i, call in enumerate(turn.tool_calls):
            rc = result_chars.get(call.id)
            spawn = agent_ids.get(call.id) if call.name in _SUBAGENT_SPAWN_TOOLS else None
            if rc is not None or spawn is not None:
                turn.tool_calls[i] = ToolCall(
                    id=call.id, name=call.name, is_mcp=call.is_mcp,
                    mcp_server=call.mcp_server, caller_type=call.caller_type,
                    input=call.input, result_tool_use_id=call.id,
                    result_chars=rc, spawned_subagent=spawn, ts=call.ts,
                    turn_uuid=call.turn_uuid,
                )


def _find_tool_result_id(message: dict) -> str | None:
    if not isinstance(message, dict):
        return None
    for blk in _content_blocks(message):
        if isinstance(blk, dict) and blk.get("type") == "tool_result":
            return blk.get("tool_use_id")
    return None


def _build_subagent(sf: SessionFiles, log: Path) -> SubagentRun | None:
    agent_id = log.stem[len("agent-"):]
    meta = load_meta(sf.subagent_metas[agent_id]) if agent_id in sf.subagent_metas else {}
    turns: list[Turn] = []
    for rec in iter_records(log):
        if rec.get("type") in _NON_TURN_TYPES:
            continue
        t = _build_turn(rec)
        if t is not None:
            turns.append(t)
    return SubagentRun(
        agent_id=agent_id,
        agent_type=meta.get("agentType"),
        description=meta.get("description"),
        parent_tool_use_id=meta.get("toolUseId"),
        turns=turns,
    )


def _attach_rollups(session: Session, raw_records: list[dict]) -> None:
    """Fill SubagentRun rollup fields from parent toolUseResult (cross-check)."""
    by_agent = {s.agent_id: s for s in session.subagents}
    for rec in raw_records:
        tur = rec.get("toolUseResult")
        if not isinstance(tur, dict):
            continue
        agent_id = tur.get("agentId")
        sub = by_agent.get(agent_id) if agent_id else None
        if sub is None:
            continue
        stats = tur.get("toolStats") if isinstance(tur.get("toolStats"), dict) else {}
        sub.resolved_model = tur.get("resolvedModel")
        sub.rollup_total_tokens = int(tur.get("totalTokens") or 0)
        sub.rollup_usage = _parse_usage(tur.get("usage"))
        sub.tool_stats = stats
        sub.total_tool_use_count = int(tur.get("totalToolUseCount") or 0)
        sub.duration_ms = int(tur.get("totalDurationMs") or 0)
        sub.agent_type = sub.agent_type or tur.get("agentType")


def assemble_session(sf: SessionFiles, project_path: str) -> Session:
    raw = list(iter_records(sf.main))
    raw_by_uuid = {r.get("uuid"): r for r in raw if r.get("uuid")}

    turns: list[Turn] = []
    started = ended = None
    cc_version = git_branch = entrypoint = None
    for rec in raw:
        if rec.get("type") in _NON_TURN_TYPES:
            continue
        cc_version = cc_version or rec.get("version")
        git_branch = git_branch or rec.get("gitBranch")
        entrypoint = entrypoint or rec.get("entrypoint")
        t = _build_turn(rec)
        if t is None:
            continue
        if not t.is_sidechain:  # main thread only at session level
            turns.append(t)
        ts = t.ts
        if ts:
            started = ts if started is None or ts < started else started
            ended = ts if ended is None or ts > ended else ended

    _link_tool_results(turns, raw_by_uuid)

    subagents = []
    for log in sf.subagent_logs:
        sub = _build_subagent(sf, log)
        if sub is not None:
            subagents.append(sub)

    session = Session(
        session_id=sf.session_id,
        project_path=project_path,
        file_path=str(sf.main),
        started_at=started,
        ended_at=ended,
        cc_version=cc_version,
        git_branch=git_branch,
        entrypoint=entrypoint,
        turns=turns,
        subagents=subagents,
    )
    _attach_rollups(session, raw)
    return session


def assemble_corpus(
    project_path: str, static: StaticEnv | None = None, scan_all: bool = False
) -> Corpus:
    """Assemble the corpus.

    Default scope is the current project (the log dir matching ``project_path``).
    ``scan_all=True`` aggregates every project under ~/.claude/projects/, labeling
    each session with its own (de-namespaced) project path.
    """
    sessions: list[Session] = []
    file_count = 0
    byte_size = 0

    if scan_all:
        for log_dir in all_project_log_dirs():
            sfs = discover_sessions_in_dir(log_dir)
            if not sfs:
                continue
            label = denamespace(log_dir.name)
            sessions.extend(assemble_session(sf, label) for sf in sfs)
            file_count += sum(1 + len(sf.subagent_logs) for sf in sfs)
            byte_size += corpus_byte_size(sfs)
        corpus_label = "<all projects>"
    else:
        sfs = discover_sessions(project_path)
        sessions = [assemble_session(sf, project_path) for sf in sfs]
        file_count = sum(1 + len(sf.subagent_logs) for sf in sfs)
        byte_size = corpus_byte_size(sfs)
        corpus_label = project_path

    cc_versions = {s.cc_version for s in sessions if s.cc_version}
    return Corpus(
        project_path=corpus_label,
        sessions=sessions,
        static=static or StaticEnv(),
        cc_versions=cc_versions,
        file_count=file_count,
        byte_size=byte_size,
    )
