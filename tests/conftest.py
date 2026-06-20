"""Shared fixtures + builders for synthetic sessions and JSONL records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tokenomics.config import Config
from tokenomics.model import (
    Corpus,
    Session,
    StaticEnv,
    SubagentRun,
    TokenUsage,
    ToolCall,
    Turn,
)

_TS = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def usage(input=0, output=0, cache_creation=0, cache_read=0, e5m=0, e1h=0) -> TokenUsage:
    return TokenUsage(
        input=input, output=output, cache_creation=cache_creation,
        cache_read=cache_read, ephemeral_5m=e5m, ephemeral_1h=e1h,
    )


def tool(name, tid="t1", inp=None, result_chars=None, spawned=None, is_mcp=False,
         server=None) -> ToolCall:
    return ToolCall(
        id=tid, name=name, is_mcp=is_mcp, mcp_server=server,
        input=inp or {}, result_chars=result_chars, spawned_subagent=spawned, ts=_TS,
    )


def turn(uuid="u1", model="claude-opus-4-8", u=None, tools=None, thinking=0,
         text=0, plugin=None, skill=None, parent=None, sidechain=False) -> Turn:
    return Turn(
        uuid=uuid, parent_uuid=parent, ts=_TS, role="assistant", model=model,
        usage=u, thinking_chars=thinking, text_chars=text, tool_calls=tools or [],
        is_sidechain=sidechain, attribution_plugin=plugin, attribution_skill=skill,
    )


def session(sid="s1", turns=None, subs=None) -> Session:
    return Session(session_id=sid, project_path="/tmp/proj", file_path="/tmp/proj/x.jsonl",
                   turns=turns or [], subagents=subs or [])


def subagent(agent_id="a1", agent_type=None, desc=None, turns=None, model=None,
             rollup_total=0) -> SubagentRun:
    return SubagentRun(
        agent_id=agent_id, agent_type=agent_type, description=desc,
        parent_tool_use_id="t1", resolved_model=model, rollup_total_tokens=rollup_total,
        turns=turns or [],
    )


def corpus(sessions=None, static=None) -> Corpus:
    return Corpus(project_path="/tmp/proj", sessions=sessions or [],
                  static=static or StaticEnv())


@pytest.fixture
def cfg() -> Config:
    return Config()


# ── Raw JSONL record builders (for parse/assemble tests) ─────────────────────

def rec_assistant(uuid, parent=None, model="claude-opus-4-8", usage_dict=None,
                  content=None, sidechain=False, **extra) -> dict:
    msg = {"model": model, "role": "assistant", "content": content or []}
    if usage_dict is not None:
        msg["usage"] = usage_dict
    return {"type": "assistant", "uuid": uuid, "parentUuid": parent,
            "timestamp": _TS.isoformat(), "sessionId": "s1", "isSidechain": sidechain,
            "message": msg, **extra}


def rec_user_tool_result(uuid, tool_use_id, content="ok", tool_use_result=None,
                         parent=None) -> dict:
    msg = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}]}
    rec = {"type": "user", "uuid": uuid, "parentUuid": parent,
           "timestamp": _TS.isoformat(), "sessionId": "s1", "message": msg}
    if tool_use_result is not None:
        rec["toolUseResult"] = tool_use_result
    return rec


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
