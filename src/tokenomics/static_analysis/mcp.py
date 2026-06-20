"""Collect MCP servers from project/user config + the remote auth cache."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import CLAUDE_HOME


def collect_mcp(project_path: str | Path) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    def add(name: str, kind: str, source: str):
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "type": kind, "source": source})

    # Project .mcp.json
    for cand, src in [
        (Path(project_path) / ".mcp.json", "project"),
        (CLAUDE_HOME / "settings.json", "user-settings"),
    ]:
        try:
            data = json.loads(cand.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        servers = data.get("mcpServers") or data.get("mcp_servers") or {}
        for name, cfg in servers.items() if isinstance(servers, dict) else []:
            add(name, (cfg or {}).get("type", "stdio"), src)

    # Remote (claude.ai-managed) servers, tracked only by the auth cache.
    cache = CLAUDE_HOME / "mcp-needs-auth-cache.json"
    try:
        data = json.loads(cache.read_text())
        for name in data if isinstance(data, dict) else []:
            add(name, "remote", "auth-cache")
    except (OSError, json.JSONDecodeError):
        pass
    return out
