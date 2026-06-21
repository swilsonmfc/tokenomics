"""Threshold flagging over newly-seen records; append-only to capture.jsonl."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ..assemble import _parse_usage  # reuse the tolerant usage parser
from ..config import OUTPUT_DIRNAME, Config


def _capture_path(project_dir: Path) -> Path:
    d = project_dir / OUTPUT_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d / "capture.jsonl"


def append_flag(project_dir: Path, flag: dict) -> None:
    flag = {"ts": datetime.now(UTC).isoformat(), **flag}
    try:
        with _capture_path(project_dir).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(flag) + "\n")
    except OSError:
        pass


def evaluate_records(
    project_dir: Path, session_id: str, records: list[dict], cfg: Config,
    cumulative: dict,
) -> list[str]:
    """Update running totals from new records; append + return warning strings."""
    th = cfg.thresholds
    warnings: list[str] = []
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        usage = _parse_usage(msg.get("usage")) if isinstance(msg, dict) else None
        if usage is None:
            continue
        cumulative["tokens"] = cumulative.get("tokens", 0) + usage.total_tokens
        ctx = usage.context_size
        cumulative["peak_context"] = max(cumulative.get("peak_context", 0), ctx)

        if ctx > th.ctx_peak:
            w = f"context window at {ctx:,} tokens (> {th.ctx_peak:,})"
            warnings.append(w)
            append_flag(project_dir, {"session": session_id, "type": "context_peak",
                                      "context_tokens": ctx})
        if (usage.cache_creation > th.cache_bust_min_creation
                and usage.cache_read < usage.cache_creation * th.cache_bust_read_ratio):
            warnings.append(f"cache bust: wrote {usage.cache_creation:,} cache tokens, "
                            f"read {usage.cache_read:,}")
            append_flag(project_dir, {"session": session_id, "type": "cache_bust",
                                      "cache_creation": usage.cache_creation,
                                      "cache_read": usage.cache_read})
        budget = cfg.session_token_budget
        if budget and cumulative["tokens"] > budget:
            warnings.append(f"session spend {cumulative['tokens']:,} tokens "
                            f"(> budget {budget:,})")
            append_flag(project_dir, {"session": session_id, "type": "budget",
                                      "tokens": cumulative["tokens"]})
    return warnings
