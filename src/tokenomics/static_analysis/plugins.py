"""Enumerate installed plugins from ~/.claude/plugins/installed_plugins.json."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import CLAUDE_HOME


def collect_plugins() -> list[dict]:
    path = CLAUDE_HOME / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict] = []
    for key, entries in (data.get("plugins") or {}).items():
        name = key.split("@")[0]
        for e in entries if isinstance(entries, list) else []:
            out.append({
                "name": name,
                "key": key,
                "version": e.get("version"),
                "installPath": e.get("installPath"),
                "scope": e.get("scope"),
            })
    return out


def plugin_roots(plugins: list[dict]) -> list[Path]:
    roots = []
    for p in plugins:
        ip = p.get("installPath")
        if ip and Path(ip).is_dir():
            roots.append(Path(ip))
    return roots
