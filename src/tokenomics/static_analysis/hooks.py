"""Parse hook configs from plugin <root>/hooks/hooks.json and settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import CLAUDE_HOME


def _parse_hooks_block(block: dict, source: str) -> list[dict]:
    out = []
    for event, entries in (block or {}).items():
        for entry in entries if isinstance(entries, list) else []:
            for h in entry.get("hooks", []) if isinstance(entry, dict) else []:
                out.append({
                    "event": event,
                    "matcher": entry.get("matcher"),
                    "command": h.get("command", "")[:200],
                    "timeout": h.get("timeout"),
                    "source": source,
                })
    return out


def collect_hooks(plugin_roots: list[Path]) -> list[dict]:
    out: list[dict] = []
    # User settings.json
    settings = CLAUDE_HOME / "settings.json"
    try:
        data = json.loads(settings.read_text())
        out.extend(_parse_hooks_block(data.get("hooks", {}), "user-settings"))
    except (OSError, json.JSONDecodeError):
        pass
    # Plugin hooks.json
    for root in plugin_roots:
        hp = root / "hooks" / "hooks.json"
        try:
            data = json.loads(hp.read_text())
            out.extend(_parse_hooks_block(data.get("hooks", {}), root.name))
        except (OSError, json.JSONDecodeError):
            continue
    return out
