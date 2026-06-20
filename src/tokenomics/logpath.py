"""Discover session + subagent log files for a project.

Layout under ``~/.claude/projects/<namespaced>/``:
  * ``<sessionId>.jsonl``                     — one top-level session
  * ``<sessionId>/subagents/agent-<id>.jsonl`` — a subagent transcript
  * ``<sessionId>/subagents/agent-<id>.meta.json`` — {agentType, description, toolUseId}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PROJECTS_DIR, namespaced_dir


@dataclass(frozen=True)
class SessionFiles:
    session_id: str
    main: Path
    subagent_logs: list[Path]   # agent-<id>.jsonl
    subagent_metas: dict[str, Path]  # agentId -> agent-<id>.meta.json


def project_log_dir(project_abs_path: str | Path) -> Path:
    return PROJECTS_DIR / namespaced_dir(project_abs_path)


def discover_sessions(project_abs_path: str | Path) -> list[SessionFiles]:
    """Enumerate session files (+ their subagent transcripts) for a project."""
    root = project_log_dir(project_abs_path)
    if not root.is_dir():
        return []
    out: list[SessionFiles] = []
    for main in sorted(root.glob("*.jsonl")):
        session_id = main.stem
        sub_dir = root / session_id / "subagents"
        logs: list[Path] = []
        metas: dict[str, Path] = {}
        if sub_dir.is_dir():
            for f in sorted(sub_dir.glob("agent-*.jsonl")):
                logs.append(f)
            for m in sub_dir.glob("agent-*.meta.json"):
                agent_id = m.name[len("agent-"):-len(".meta.json")]
                metas[agent_id] = m
        out.append(SessionFiles(session_id, main, logs, metas))
    return out


def corpus_byte_size(sessions: list[SessionFiles]) -> int:
    total = 0
    for s in sessions:
        try:
            total += s.main.stat().st_size
        except OSError:
            pass
        for log in s.subagent_logs:
            try:
                total += log.stat().st_size
            except OSError:
                pass
    return total
