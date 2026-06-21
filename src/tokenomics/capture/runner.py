"""Hook entrypoint for capture mode.

Reads the hook event JSON on stdin, finds the live session transcript, parses
only the newly-appended records, flags waste, and prints a short warning the
agent sees before the next turn. Always exits 0, fast, append-only — a capture
hook must never disrupt the session.

Hook payload fields used: ``session_id``, ``cwd``, ``transcript_path``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import OUTPUT_DIRNAME, load_config
from ..logpath import project_log_dir
from .flags import append_flag, evaluate_records
from .tailer import read_new_records, reset_offset


def _read_event() -> dict:
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_transcript(event: dict, project_dir: Path, session_id: str) -> Path | None:
    tp = event.get("transcript_path")
    if tp and Path(tp).exists():
        return Path(tp)
    # Fall back to ~/.claude/projects/<namespaced>/<session>.jsonl
    if session_id:
        cand = project_log_dir(project_dir) / f"{session_id}.jsonl"
        if cand.exists():
            return cand
    return None


def _running_path(project_dir: Path, session_id: str) -> Path:
    d = project_dir / OUTPUT_DIRNAME / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"running-{session_id}.json"


def _load_running(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def dispatch(event_name: str) -> int:
    event = _read_event()
    session_id = event.get("session_id") or "unknown"
    project_dir = Path(event.get("cwd") or ".").resolve()
    cfg = load_config(str(project_dir))
    if not cfg.capture_enabled:
        return 0

    if event_name == "session-start":
        reset_offset(project_dir, session_id)
        append_flag(project_dir, {"session": session_id, "type": "session_start"})
        return 0

    transcript = _resolve_transcript(event, project_dir, session_id)
    if transcript is None:
        return 0

    records = read_new_records(project_dir, session_id, transcript)
    run_path = _running_path(project_dir, session_id)
    cumulative = _load_running(run_path)
    warnings = evaluate_records(project_dir, session_id, records, cfg, cumulative)
    try:
        run_path.write_text(json.dumps(cumulative))
    except OSError:
        pass

    if event_name == "stop":
        append_flag(project_dir, {"session": session_id, "type": "session_summary",
                                  "tokens": cumulative.get("tokens", 0),
                                  "peak_context": cumulative.get("peak_context", 0)})

    if warnings:
        # Surfaced to the agent as additional context before the next turn.
        print("[tokenomics] " + "; ".join(warnings[:3]))
    return 0


def set_enabled(project_path: str, enabled: bool) -> None:
    """Toggle capture.enabled in .tokenomics/config.toml (create if needed)."""
    out = Path(project_path) / OUTPUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    toml_path = out / "config.toml"
    lines = []
    if toml_path.exists():
        lines = [
            ln for ln in toml_path.read_text().splitlines()
            if not ln.strip().startswith("capture_enabled")
        ]
    lines.append(f"capture_enabled = {'true' if enabled else 'false'}")
    toml_path.write_text("\n".join(lines) + "\n")
