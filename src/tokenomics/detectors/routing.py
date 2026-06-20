"""D2 — Routing intelligence: right model & thinking for the work?"""

from __future__ import annotations

from collections import Counter

from .. import pricing
from ..config import MODEL_TIER, Config
from ..model import Corpus
from ._util import all_turns
from .base import Confidence, Finding, Severity


class RoutingDetector:
    id = "routing"
    title = "Routing intelligence"
    analysis_no = 2

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        tokens_by_model: Counter[str] = Counter()
        trivial_premium_tokens = 0
        trivial_premium_turns = 0
        total_turns = 0

        for turn, default_model, _ in all_turns(corpus):
            if turn.usage is None or turn.usage.total_tokens == 0:
                continue
            total_turns += 1
            model = pricing.normalize_model(turn.model or default_model) or "unknown"
            tokens_by_model[model] += turn.usage.total_tokens
            tier = MODEL_TIER.get(model, 0)
            is_premium = tier >= 3
            is_trivial = (
                turn.usage.output < th.trivial_output_tokens
                and not turn.tool_calls
                and turn.thinking_chars == 0
            )
            if is_premium and is_trivial:
                trivial_premium_turns += 1
                trivial_premium_tokens += turn.usage.total_tokens

        if not tokens_by_model:
            return []

        findings: list[Finding] = []
        total_tokens = sum(tokens_by_model.values())
        top_model, top_tokens = tokens_by_model.most_common(1)[0]
        top_share = top_tokens / total_tokens

        # Real counterfactual: the trivial-premium tokens re-priced on a cheap tier.
        # A firm price delta (HIGH confidence) — lo == hi, no fudge fraction.
        cheap = "claude-haiku-4-5"
        prem_in = pricing.tokens_cost_usd(trivial_premium_tokens, top_model, "input")
        cheap_in = pricing.tokens_cost_usd(trivial_premium_tokens, cheap, "input")
        save_usd = round(prem_in - cheap_in, 4) if (prem_in and cheap_in) else None
        routing_savings = {
            "est_savings_tokens": trivial_premium_tokens or None,
            "est_savings_usd": save_usd,
            "est_savings_usd_lo": save_usd,
            "est_savings_usd_hi": save_usd,
            "est_savings_weight": save_usd if save_usd is not None
            else trivial_premium_tokens / 1_000_000 * 4,
            "confidence": Confidence.HIGH,
        }

        if MODEL_TIER.get(top_model, 0) >= 3 and top_share >= th.opus_share:
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no,
                severity=Severity.HIGH,
                title=f"Opus-everywhere: {top_share:.0%} of tokens on {top_model}",
                evidence={
                    "top_model": top_model,
                    "top_share": round(top_share, 3),
                    "tokens_by_model": dict(tokens_by_model.most_common()),
                    "trivial_premium_turns": trivial_premium_turns,
                    "trivial_premium_tokens": trivial_premium_tokens,
                },
                recommendation=(
                    "Route trivial/mechanical turns (short output, no tools, no "
                    "thinking) to a cheaper model, and pin cheap subagents via "
                    "agent `model:` frontmatter. Reserve the premium model for "
                    "hard reasoning. See the dynamic-router-advisor skill."
                ),
                pattern_id="routing.premium-everywhere",
                deep_enrichable=True,
                **routing_savings,
            ))

        if trivial_premium_turns and total_turns:
            ratio = trivial_premium_turns / total_turns
            if ratio >= 0.15 and not findings:
                findings.append(Finding(
                    detector_id=self.id, analysis_no=self.analysis_no,
                    severity=Severity.MED,
                    title=f"{ratio:.0%} of turns are trivial work on a premium model",
                    evidence={"trivial_premium_turns": trivial_premium_turns,
                              "total_turns": total_turns},
                    recommendation="Downshift trivial turns to a cheaper model tier.",
                    pattern_id="routing.premium-everywhere",
                    deep_enrichable=True,
                    **{**routing_savings, "confidence": Confidence.MED},
                ))
        return findings


DETECTOR = RoutingDetector()
