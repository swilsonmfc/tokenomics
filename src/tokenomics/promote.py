"""Promote mined ``candidate`` patterns to ``empirical``.

A candidate is a one-shot correlation from a single ``mine`` run. Promotion is
the gate that turns it into a trusted (fires-by-default) ``empirical`` record. To
qualify, a candidate must:

  1. **be stable** — reappear when the current corpus is re-mined, and
  2. **separate strongly** — its re-mined cohort separation is at or above
     ``Thresholds.promote_min_separation``.

Promoted records move from ``.tokenomics/taxonomy/mined.toml`` into
``promoted.toml`` (id renamed ``mined.*`` → ``empirical.*``, maturity flipped),
so the next scan fires them like any curated pattern. Nothing is promoted that a
fresh mine of today's data does not still support.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .config import Config
from .miner import mine
from .model import Corpus
from .taxonomy import (
    PROJECT_CATALOG_SUBDIR,
    Pattern,
    dump_patterns_toml,
    load_patterns_file,
)

_MINED_FILE = "mined.toml"
_PROMOTED_FILE = "promoted.toml"


@dataclass
class PromotionResult:
    promoted: list[Pattern] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (id, reason)
    reason: str = ""  # set when nothing could be attempted at all

    @property
    def ok(self) -> bool:
        return bool(self.promoted)


def _candidate_id_to_empirical(pid: str) -> str:
    return "empirical." + pid.split(".", 1)[-1]


def promote_candidates(
    project_path: str | Path,
    cfg: Config,
    corpus: Corpus,
    *,
    pattern_ids: list[str] | None = None,
    today: str = "",
) -> PromotionResult:
    """Promote qualifying candidates from mined.toml into promoted.toml.

    ``pattern_ids`` limits promotion to named candidates; ``None`` considers every
    candidate (``--all-qualifying``). ``corpus`` is re-mined for the stability check.
    """
    tax_dir = Path(project_path) / PROJECT_CATALOG_SUBDIR
    mined_path = tax_dir / _MINED_FILE
    if not mined_path.exists():
        return PromotionResult(reason="no mined.toml — run `tokenomics mine` first")

    candidates = {p.id: p for p in load_patterns_file(mined_path)
                  if p.maturity == "candidate"}
    if not candidates:
        return PromotionResult(reason="no candidate patterns in mined.toml")

    # Stability gate: a candidate must still surface when we re-mine right now.
    remine = {f.pattern.id: f for f in mine(corpus, cfg, today=today).findings}

    selected = pattern_ids or list(candidates)
    result = PromotionResult()
    promoted_src_ids: set[str] = set()
    bar = cfg.thresholds.promote_min_separation
    for pid in selected:
        if pid not in candidates:
            result.skipped.append((pid, "not a current candidate"))
            continue
        mf = remine.get(pid)
        if mf is None:
            result.skipped.append((pid, "did not reappear on re-mine (unstable)"))
            continue
        if mf.separation < bar:
            result.skipped.append(
                (pid, f"separation {mf.separation:.2f} < {bar:.2f} bar"))
            continue
        # Promote the *freshly re-mined* pattern (current threshold), flipped.
        base = mf.pattern
        result.promoted.append(replace(
            base,
            id=_candidate_id_to_empirical(base.id),
            maturity="empirical",
            provenance=f"{base.provenance}; promoted {today} (sep {mf.separation:.2f})",
            reviewed=today or base.reviewed,
        ))
        promoted_src_ids.add(pid)

    if result.promoted:
        _merge_promoted(tax_dir, result.promoted, today)
        _rewrite_mined(mined_path, candidates, promoted_src_ids, today)
    return result


def _merge_promoted(tax_dir: Path, new: list[Pattern], today: str) -> None:
    path = tax_dir / _PROMOTED_FILE
    existing = {p.id: p for p in load_patterns_file(path)} if path.exists() else {}
    for p in new:
        existing[p.id] = p  # newest promotion wins on re-promote
    header = (f"Promoted empirical patterns (last updated {today}). Stability- and "
              "separation-gated from mined candidates; these fire by default.")
    path.write_text(dump_patterns_toml(
        sorted(existing.values(), key=lambda p: p.id), header))


def _rewrite_mined(mined_path: Path, candidates: dict[str, Pattern],
                   promoted_src_ids: set[str], today: str) -> None:
    remaining = [p for pid, p in candidates.items() if pid not in promoted_src_ids]
    if not remaining:
        mined_path.unlink()
        return
    header = (f"Mined candidate patterns (pruned {today} after promotion). "
              "Correlational — review before trusting.")
    mined_path.write_text(dump_patterns_toml(
        sorted(remaining, key=lambda p: p.id), header))
