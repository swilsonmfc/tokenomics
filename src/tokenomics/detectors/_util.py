"""Shared helpers for detectors."""

from __future__ import annotations

from collections.abc import Iterator

# Search-call detection lives in features (the shared substrate) to keep a single
# definition; re-exported here so detectors keep importing it from _util.
from ..features import SEARCH_BASH as SEARCH_BASH_RE
from ..features import SEARCH_TOOLS, is_search_call
from ..model import Corpus, Session, Turn

REVIEW_PAT = ("review", "critique", "security", "audit", "verify", "lint")

__all__ = ["all_turns", "is_search_call", "looks_review", "SEARCH_TOOLS", "SEARCH_BASH_RE"]


def all_turns(corpus: Corpus) -> Iterator[tuple[Turn, str | None, Session]]:
    """Yield (turn, default_model, session) across main threads and subagents."""
    for session in corpus.sessions:
        for turn in session.turns:
            yield turn, None, session
        for sub in session.subagents:
            for turn in sub.turns:
                yield turn, sub.model, session


def looks_review(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(p in low for p in REVIEW_PAT)
