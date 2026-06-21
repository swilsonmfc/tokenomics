"""Stream raw JSONL records, tolerant of malformed lines and schema drift.

This layer does no interpretation — it yields plain dicts. ``assemble`` turns
them into the model. Keep it dumb so two log generations both flow through.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path


def iter_records(path: Path) -> Iterator[dict]:
    """Yield one dict per line; silently skip blank/malformed lines."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def load_meta(path: Path) -> dict:
    """Load an ``agent-<id>.meta.json`` (best-effort)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
