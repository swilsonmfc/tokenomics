"""Parse agent definitions from plugin <root>/agents/*.md and ~/.claude/agents."""

from __future__ import annotations

from pathlib import Path

from ..config import CLAUDE_HOME
from ._frontmatter import read_frontmatter


def _scan(agents_dir: Path, source: str) -> list[dict]:
    out = []
    if not agents_dir.is_dir():
        return out
    for af in sorted(agents_dir.glob("*.md")):
        fm, _ = read_frontmatter(af)
        out.append({
            "name": fm.get("name") or af.stem,
            "description": fm.get("description", ""),
            "model": fm.get("model"),  # None = inherits (no cheap-model pin)
            "tools": fm.get("tools"),
            "source": source,
            "path": str(af),
        })
    return out


def collect_agents(plugin_roots: list[Path]) -> list[dict]:
    out = _scan(CLAUDE_HOME / "agents", "user")
    for root in plugin_roots:
        out.extend(_scan(root / "agents", root.name))
    return out
