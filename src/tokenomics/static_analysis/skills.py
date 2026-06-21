"""Parse skills from plugin <root>/skills/<name>/SKILL.md and ~/.claude/skills."""

from __future__ import annotations

from pathlib import Path

from ..config import CLAUDE_HOME
from ._frontmatter import read_frontmatter


def _scan(skills_dir: Path, source: str) -> list[dict]:
    out = []
    if not skills_dir.is_dir():
        return out
    for sk in sorted(skills_dir.glob("*/SKILL.md")):
        fm, body_lines = read_frontmatter(sk)
        out.append({
            "name": fm.get("name") or sk.parent.name,
            "description": fm.get("description", ""),
            "body_lines": body_lines,
            "source": source,
            "path": str(sk),
        })
    return out


def collect_skills(plugin_roots: list[Path]) -> list[dict]:
    out = _scan(CLAUDE_HOME / "skills", "user")
    for root in plugin_roots:
        out.extend(_scan(root / "skills", root.name))
    return out
