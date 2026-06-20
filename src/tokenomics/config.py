"""Configuration: paths, detector thresholds, model pricing, aliases.

Thresholds are overridable per-project via ``.tokenomics/config.toml`` (loaded by
``load_config``). Pricing is sourced from the ``claude-api`` skill (cached
2026-06) — see ``MODEL_PRICES``; update it there, not from memory.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"
OUTPUT_DIRNAME = ".tokenomics"


def namespaced_dir(project_abs_path: str | Path) -> str:
    """Map a project path to its log-folder name.

    Claude Code names the folder by replacing ``/`` (and ``.``) with ``-`` in the
    absolute path: ``/Users/x/Projects/foo`` -> ``-Users-x-Projects-foo``.
    """
    p = str(Path(project_abs_path).resolve())
    return p.replace("/", "-").replace(".", "-")


# ── Pricing (USD per 1M tokens; from the claude-api skill, cached 2026-06) ───
# Cache economics (all models): read ≈ 0.1× input; write_5m ≈ 1.25× input;
# write_1h ≈ 2× input. Opus 4.6+ / Sonnet 4.6 / Fable 5 are flat-priced at 1M
# context — there is NO long-context premium, so the "[1m]" resolvedModel tag
# does not select a different rate.

CACHE_READ_MULT = 0.10
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.00


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float

    @property
    def cache_read_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_READ_MULT

    @property
    def cache_write_5m_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_WRITE_5M_MULT

    @property
    def cache_write_1h_per_mtok(self) -> float:
        return self.input_per_mtok * CACHE_WRITE_1H_MULT


# Keyed by normalized model id (see pricing.normalize_model).
MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-fable-5": ModelPrice(10.0, 50.0),
    "claude-mythos-5": ModelPrice(10.0, 50.0),
    "claude-opus-4-8": ModelPrice(5.0, 25.0),
    "claude-opus-4-7": ModelPrice(5.0, 25.0),
    "claude-opus-4-6": ModelPrice(5.0, 25.0),
    "claude-opus-4-5": ModelPrice(5.0, 25.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-sonnet-4-5": ModelPrice(3.0, 15.0),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0),
}

# Relative weight (vs the cheapest priced model) used to rank spend even when a
# model is unpriced — based on input rate. Cheapest priced input rate = $1/Mtok.
RELATIVE_WEIGHT_BASE = 1.0

# Model tiers for routing analysis (higher = more expensive/capable).
MODEL_TIER = {
    "claude-haiku-4-5": 1,
    "claude-sonnet-4-6": 2,
    "claude-sonnet-4-5": 2,
    "claude-opus-4-5": 3,
    "claude-opus-4-6": 3,
    "claude-opus-4-7": 3,
    "claude-opus-4-8": 3,
    "claude-fable-5": 4,
    "claude-mythos-5": 4,
}


# ── Detector thresholds ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Thresholds:
    # D1 search efficiency
    search_ratio: float = 0.35
    search_min_calls: int = 8
    repeat_grep: int = 3
    search_reduction_factor: float = 0.5
    # D2 routing
    opus_share: float = 0.8
    trivial_output_tokens: int = 120
    # D3 context window
    ctx_peak: int = 150_000
    ctx_avg: int = 80_000
    # D4 CLAUDE.md
    claudemd_tokens: int = 2_000
    claudemd_lines: int = 200
    # D5 cache busting
    cache_efficiency: float = 0.60
    # D6 review agents
    review_dup: int = 2
    # D7 second tier
    reread: int = 3
    fanout: int = 6
    tool_result_bloat_chars: int = 50_000


@dataclass(frozen=True)
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)
    # Optional spend budget per session (tokens) used by capture-mode flagging.
    session_token_budget: int | None = None
    capture_enabled: bool = True


def load_config(project_path: str | Path) -> Config:
    """Load ``.tokenomics/config.toml`` overrides if present, else defaults."""
    cfg = Config()
    toml_path = Path(project_path) / OUTPUT_DIRNAME / "config.toml"
    if not toml_path.exists():
        return cfg
    try:
        data = tomllib.loads(toml_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return cfg
    th = data.get("thresholds", {})
    if th:
        cfg = replace(cfg, thresholds=replace(cfg.thresholds, **{
            k: v for k, v in th.items() if hasattr(cfg.thresholds, k)
        }))
    if "session_token_budget" in data:
        cfg = replace(cfg, session_token_budget=data["session_token_budget"])
    if "capture_enabled" in data:
        cfg = replace(cfg, capture_enabled=bool(data["capture_enabled"]))
    return cfg
