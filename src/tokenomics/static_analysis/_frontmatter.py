"""Minimal YAML-frontmatter reader (name/description/model/etc.) — no PyYAML dep.

Handles the simple ``key: value`` frontmatter used by SKILL.md / agent .md files.
"""

from __future__ import annotations

from pathlib import Path


def read_frontmatter(path: Path) -> tuple[dict, int]:
    """Return (frontmatter dict, body line count)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, 0
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, len(lines)
    fm: dict[str, str] = {}
    body_start = len(lines)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
        if ":" in lines[i]:
            k, _, v = lines[i].partition(":")
            fm[k.strip()] = v.strip().strip("'\"")
    return fm, len(lines) - body_start
