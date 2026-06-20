"""Token → cost conversion across mixed models.

Two outputs per usage:
  * absolute USD — when the model is priced in ``config.MODEL_PRICES``
  * relative weight — a normalized "token-dollar" unit so unpriced/unknown
    models still rank in findings (based on the model's input rate, or a
    neutral default when unknown).

Model-id normalization strips the ``[1m]`` context-window tag (which is NOT a
price premium on current models) and any ``us.anthropic.`` / ``anthropic.``
provider prefixes, then applies a small alias map.
"""

from __future__ import annotations

import re

from .config import MODEL_PRICES, ModelPrice
from .model import TokenUsage

_TAG_RE = re.compile(r"\[[^\]]*\]$")  # trailing "[1m]" etc.
_PREFIX_RE = re.compile(r"^(us\.|eu\.)?anthropic\.")
_DATE_RE = re.compile(r"-\d{8}$")  # trailing dated snapshot "-20251001"

# Neutral fallback used for relative-weight ranking of unpriced models.
_DEFAULT_INPUT_RATE = 5.0  # opus-tier assumption keeps unknown spend visible


def normalize_model(model: str | None) -> str | None:
    if not model:
        return None
    m = model.strip()
    m = _PREFIX_RE.sub("", m)
    m = _TAG_RE.sub("", m)
    m = _DATE_RE.sub("", m)
    return m or None


def price_for(model: str | None) -> ModelPrice | None:
    norm = normalize_model(model)
    if norm is None:
        return None
    return MODEL_PRICES.get(norm)


def usage_cost_usd(usage: TokenUsage, model: str | None) -> float | None:
    """Absolute USD for one usage, or None when the model is unpriced."""
    price = price_for(model)
    if price is None:
        return None
    per_mtok = 1_000_000.0
    cost = (
        usage.input * price.input_per_mtok
        + usage.output * price.output_per_mtok
        + usage.cache_read * price.cache_read_per_mtok
        + usage.ephemeral_5m * price.cache_write_5m_per_mtok
        + usage.ephemeral_1h * price.cache_write_1h_per_mtok
    )
    # cache_creation not split into 5m/1h (older logs): bill at 5m rate, minus
    # whatever was already attributed via the ephemeral_* breakdown.
    leftover_creation = usage.cache_creation - usage.ephemeral_5m - usage.ephemeral_1h
    if leftover_creation > 0:
        cost += leftover_creation * price.cache_write_5m_per_mtok
    return cost / per_mtok


def usage_weight(usage: TokenUsage, model: str | None) -> float:
    """Relative-weight token-dollars; always defined (ranks unpriced models)."""
    price = price_for(model)
    in_rate = price.input_per_mtok if price else _DEFAULT_INPUT_RATE
    out_rate = price.output_per_mtok if price else _DEFAULT_INPUT_RATE * 5
    per_mtok = 1_000_000.0
    weighted = (
        usage.fresh_input * in_rate
        + usage.output * out_rate
        + usage.cache_read * in_rate * 0.10
    )
    return weighted / per_mtok


def tokens_cost_usd(tokens: int, model: str | None, kind: str = "input") -> float | None:
    """Cost of a flat token count at a model's input/output rate (for savings est.)."""
    price = price_for(model)
    if price is None:
        return None
    rate = price.output_per_mtok if kind == "output" else price.input_per_mtok
    return tokens * rate / 1_000_000.0
