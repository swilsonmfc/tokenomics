"""Incremental reader of a live session jsonl using a byte-offset cache.

Each capture invocation parses only new lines since the last call, keyed by
sessionId, so PostToolUse never re-parses the whole (possibly multi-MB) file.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import OUTPUT_DIRNAME


def _offset_path(project_dir: Path, session_id: str) -> Path:
    d = project_dir / OUTPUT_DIRNAME / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"offset-{session_id}.json"


def read_new_records(project_dir: Path, session_id: str, log_path: Path) -> list[dict]:
    """Return records appended since the last call; advance the offset."""
    off_path = _offset_path(project_dir, session_id)
    start = 0
    if off_path.exists():
        try:
            start = int(json.loads(off_path.read_text()).get("offset", 0))
        except (OSError, json.JSONDecodeError, ValueError):
            start = 0
    records: list[dict] = []
    new_offset = start
    try:
        size = log_path.stat().st_size
        if size < start:  # file rotated/truncated — restart from the top
            start = 0
            new_offset = 0
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            for line in fh:
                new_offset += len(line.encode("utf-8"))
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    except OSError:
        return []
    try:
        off_path.write_text(json.dumps({"offset": new_offset}))
    except OSError:
        pass
    return records


def reset_offset(project_dir: Path, session_id: str) -> None:
    off_path = _offset_path(project_dir, session_id)
    try:
        off_path.write_text(json.dumps({"offset": 0}))
    except OSError:
        pass
