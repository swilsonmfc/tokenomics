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

from .config import (
    CACHE_READ_MULT,
    CACHE_WRITE_5M_MULT,
    MODEL_PRICES,
    ModelPrice,
)
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


# Per-token rate ($/Mtok) for each savings "kind". The premium of a cache write
# over the cache read it should have been is (write_5m − read) × input.
_CACHE_PREMIUM_MULT = CACHE_WRITE_5M_MULT - CACHE_READ_MULT


def _priced_rate(price: ModelPrice | None, kind: str) -> float | None:
    """USD/Mtok for a savings kind, or None when the model is unpriced."""
    if price is None:
        return None
    if kind == "output":
        return price.output_per_mtok
    if kind == "cache_premium":
        return price.input_per_mtok * _CACHE_PREMIUM_MULT
    if kind == "cache_read":
        return price.cache_read_per_mtok
    return price.input_per_mtok  # "input"


def _weight_rate(price: ModelPrice | None, kind: str) -> float:
    """USD/Mtok for ranking — always defined (falls back for unpriced models)."""
    rate = _priced_rate(price, kind)
    if rate is not None:
        return rate
    base = _DEFAULT_INPUT_RATE
    if kind == "output":
        return base * 5
    if kind == "cache_premium":
        return base * _CACHE_PREMIUM_MULT
    if kind == "cache_read":
        return base * CACHE_READ_MULT
    return base


def savings_weight(tokens: float, model: str | None, kind: str = "input") -> float:
    """Ranking weight (token-dollars) for a flat avoidable token volume.

    The model-aware analogue of a hardcoded multiplier: priced models use their
    real rate, unpriced models fall back to the neutral default — the same basis
    ``estimate_savings``/``usage_weight`` use, so weights stay comparable.
    """
    return max(0.0, tokens) * _weight_rate(price_for(model), kind) / 1_000_000.0


def estimate_savings(
    avoidable_tokens: int,
    model: str | None,
    *,
    kind: str = "input",
    frac: tuple[float, float] = (1.0, 1.0),
    confidence,
) -> dict:
    """Build the savings fields of a Finding from an avoidable token volume.

    ``avoidable_tokens`` is the volume already scoped to what could plausibly be
    cut (e.g. only the duplicate review runs, only repeated greps). ``frac`` is
    the (low, high) fraction of that volume realistically recoverable — the
    source of the reported USD range. ``kind`` picks the rate: ``input`` /
    ``output`` (token rates), ``cache_premium`` (a write that should have been a
    read), or ``cache_read`` (cached re-send). USD is ``None`` for unpriced
    models; ``est_savings_weight`` is always defined so the finding still ranks.

    Returns a dict splattable into ``Finding(**...)``.
    """
    lo_f, hi_f = frac
    mid_f = (lo_f + hi_f) / 2.0
    price = price_for(model)
    per_mtok = 1_000_000.0

    usd_rate = _priced_rate(price, kind)
    if usd_rate is not None:
        usd_lo = round(avoidable_tokens * lo_f * usd_rate / per_mtok, 4)
        usd_hi = round(avoidable_tokens * hi_f * usd_rate / per_mtok, 4)
        usd_mid = round((usd_lo + usd_hi) / 2.0, 4)
    else:
        usd_lo = usd_hi = usd_mid = None

    weight = avoidable_tokens * mid_f * _weight_rate(price, kind) / per_mtok
    return {
        "est_savings_tokens": int(round(avoidable_tokens * mid_f)),
        "est_savings_usd": usd_mid,
        "est_savings_usd_lo": usd_lo,
        "est_savings_usd_hi": usd_hi,
        "est_savings_weight": weight,
        "confidence": confidence,
    }
