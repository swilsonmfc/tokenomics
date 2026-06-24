"""Best-practice taxonomy: a declarative catalog of cost patterns.

The catalog (``catalog/*.toml``) is the single knowledge source describing both
anti-patterns and best practices. Each record is a ``Pattern``. Two engines:

* ``detector`` — the pattern is computed by a bespoke Python detector (the
  historical seven). The catalog record is metadata + the cross-reference: the
  detector stamps ``Finding.pattern_id`` so report/skills speak one vocabulary.
* ``declarative`` — the pattern is a boolean ``rule`` over the trajectory feature
  vector, evaluated by ``detectors/taxonomy_match.py``. New coverage with no code.

Maturity tiers gate trust: ``curated`` (authoritative), ``empirical`` (corpus-mined
and confirmed), ``candidate`` (mined, unconfirmed). The corpus miner that produces
``candidate`` records is the next phase; the schema is ready for it now.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .evaluator import RuleError, compile_rule

_CATALOG_DIR = Path(__file__).parent / "catalog"
# Mined / promoted patterns live alongside a scanned project's output.
PROJECT_CATALOG_SUBDIR = ".tokenomics/taxonomy"

# Taxonomy category → report analysis section number (keeps report grouping stable).
CATEGORY_ANALYSIS: dict[str, int] = {
    "search": 1,
    "routing": 2,
    "context": 3,
    "claudemd": 4,
    "cache": 5,
    "review": 6,
    "secondtier": 7,
    "output": 8,
}

_POLARITY = {"anti_pattern", "best_practice"}
_ENGINE = {"detector", "declarative"}
_MATURITY = {"curated", "empirical", "candidate"}
_SEVERITY = {"info", "low", "med", "high"}


@dataclass(frozen=True)
class Pattern:
    id: str
    category: str
    polarity: str
    scope: str  # turn | trajectory | session | static | corpus
    engine: str
    title: str = ""
    recommendation: str = ""
    rule: str | None = None
    detector_id: str | None = None
    signals: tuple[str, ...] = ()
    severity: str = "info"
    remediation_skill: str | None = None
    maturity: str = "curated"
    provenance: str = ""
    reviewed: str = ""
    references: tuple[str, ...] = ()

    @property
    def analysis_no(self) -> int:
        return CATEGORY_ANALYSIS.get(self.category, 0)

    def compiled(self):
        """Compile the declarative rule (raises RuleError if malformed)."""
        if self.engine != "declarative" or not self.rule:
            return None
        return compile_rule(self.rule)


def _validate(p: Pattern) -> None:
    if p.category not in CATEGORY_ANALYSIS:
        raise RuleError(f"{p.id}: unknown category {p.category!r}")
    if p.polarity not in _POLARITY:
        raise RuleError(f"{p.id}: bad polarity {p.polarity!r}")
    if p.engine not in _ENGINE:
        raise RuleError(f"{p.id}: bad engine {p.engine!r}")
    if p.maturity not in _MATURITY:
        raise RuleError(f"{p.id}: bad maturity {p.maturity!r}")
    if p.severity not in _SEVERITY:
        raise RuleError(f"{p.id}: bad severity {p.severity!r}")
    if p.engine == "declarative":
        if not p.rule:
            raise RuleError(f"{p.id}: declarative pattern needs a rule")
        p.compiled()  # compile now to surface malformed rules at load time
    if p.engine == "detector" and not p.detector_id:
        raise RuleError(f"{p.id}: detector pattern needs a detector_id")


def _coerce(raw: dict) -> Pattern:
    fields = {
        "id", "category", "polarity", "scope", "engine", "title", "recommendation",
        "rule", "detector_id", "signals", "severity", "remediation_skill",
        "maturity", "provenance", "reviewed", "references",
    }
    data = {k: v for k, v in raw.items() if k in fields}
    for seq in ("signals", "references"):
        if seq in data and isinstance(data[seq], list):
            data[seq] = tuple(data[seq])
    return Pattern(**data)


@dataclass(frozen=True)
class Catalog:
    patterns: tuple[Pattern, ...] = ()

    def declarative(self) -> list[Pattern]:
        return [p for p in self.patterns if p.engine == "declarative"]

    def by_id(self) -> dict[str, Pattern]:
        return {p.id: p for p in self.patterns}

    def by_maturity(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.patterns:
            out[p.maturity] = out.get(p.maturity, 0) + 1
        return out


def load_patterns_file(path: str | Path) -> list[Pattern]:
    """Parse + validate the patterns in a single catalog TOML file."""
    data = tomllib.loads(Path(path).read_text())
    out: list[Pattern] = []
    for raw in data.get("pattern", []):
        p = _coerce(raw)
        _validate(p)
        out.append(p)
    return out


def load_catalog(catalog_dir: Path | None = None,
                 project_path: str | Path | None = None) -> Catalog:
    """Load + validate every ``*.toml`` pattern file. Stable order by id.

    Loads the packaged curated catalog and, when ``project_path`` is given, any
    mined/promoted patterns under ``<project>/.tokenomics/taxonomy/`` too.
    """
    dirs = [catalog_dir or _CATALOG_DIR]
    if project_path is not None:
        proj = Path(project_path) / PROJECT_CATALOG_SUBDIR
        if proj.is_dir():
            dirs.append(proj)

    patterns: list[Pattern] = []
    seen: set[str] = set()
    for d in dirs:
        for toml_path in sorted(d.glob("*.toml")):
            data = tomllib.loads(toml_path.read_text())
            for raw in data.get("pattern", []):
                p = _coerce(raw)
                if p.id in seen:
                    raise RuleError(f"duplicate pattern id {p.id!r} in {toml_path.name}")
                _validate(p)
                seen.add(p.id)
                patterns.append(p)
    patterns.sort(key=lambda p: p.id)
    return Catalog(patterns=tuple(patterns))


_DUMP_ORDER = (
    "id", "category", "polarity", "scope", "engine", "rule", "detector_id",
    "signals", "severity", "remediation_skill", "maturity", "provenance",
    "reviewed", "title", "recommendation", "references",
)


def _toml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dump_patterns_toml(patterns: list[Pattern], header: str = "") -> str:
    """Serialize patterns to catalog TOML (round-trips through ``load_catalog``)."""
    lines: list[str] = []
    if header:
        lines.extend(f"# {ln}" for ln in header.splitlines())
        lines.append("")
    for p in patterns:
        lines.append("[[pattern]]")
        for fld in _DUMP_ORDER:
            val = getattr(p, fld)
            if val in (None, "", (), []):
                continue
            lines.append(f"{fld} = {_toml_scalar(val)}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "Catalog", "Pattern", "RuleError", "CATEGORY_ANALYSIS",
    "PROJECT_CATALOG_SUBDIR", "load_catalog", "load_patterns_file",
    "dump_patterns_toml",
]
