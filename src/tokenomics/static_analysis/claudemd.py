"""Locate and structurally analyze CLAUDE.md files (project + user).

Token estimate uses chars/4 (no tiktoken dependency). Detects duplicate headings
as a cheap bloat/contradiction signal.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..config import CLAUDE_HOME


def _analyze(path: Path, scope: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    headings = [ln.strip().lower() for ln in lines if ln.lstrip().startswith("#")]
    dup = [h for h, c in Counter(headings).items() if c > 1]
    return {
        "path": str(path),
        "scope": scope,
        "bytes": len(text.encode("utf-8")),
        "lines": len(lines),
        "est_tokens": len(text) // 4,
        "heading_count": len(headings),
        "duplicate_headings": dup,
    }


def collect_claude_md(project_path: str | Path) -> list[dict]:
    out = []
    for cand, scope in [
        (Path(project_path) / "CLAUDE.md", "project"),
        (CLAUDE_HOME / "CLAUDE.md", "user"),
    ]:
        if cand.exists():
            info = _analyze(cand, scope)
            if info:
                out.append(info)
    return out
