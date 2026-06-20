"""Shared helpers for detectors."""

from __future__ import annotations

from collections.abc import Iterator

from ..model import Corpus, Session, ToolCall, Turn

SEARCH_TOOLS = {"Grep", "Glob"}
SEARCH_BASH_RE = ("grep", "rg ", "ripgrep", "find ", "ag ", "ack ")
REVIEW_PAT = ("review", "critique", "security", "audit", "verify", "lint")


def all_turns(corpus: Corpus) -> Iterator[tuple[Turn, str | None, Session]]:
    """Yield (turn, default_model, session) across main threads and subagents."""
    for session in corpus.sessions:
        for turn in session.turns:
            yield turn, None, session
        for sub in session.subagents:
            for turn in sub.turns:
                yield turn, sub.model, session


def is_search_call(call: ToolCall) -> bool:
    if call.name in SEARCH_TOOLS:
        return True
    if call.name == "Bash":
        cmd = str(call.input.get("command", "")).lower()
        return any(tok in cmd for tok in SEARCH_BASH_RE)
    return False


def looks_review(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(p in low for p in REVIEW_PAT)
