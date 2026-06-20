"""--deep enrichment: ask an efficient model for semantic judgments.

Strictly ADDITIVE — it only fills ``deep_note`` on findings flagged
``deep_enrichable``; it never alters hard metrics. The model client is injected
so tests can stub it (no network in CI). Uses the cheapest capable model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

ENRICH_MODEL = "claude-haiku-4-5"  # cheap by design — this is a cost tool
MAX_FINDINGS = 12


class ModelClient(Protocol):
    def judge(self, prompt: str) -> str:
        ...


class AnthropicClient:
    """Thin wrapper over the Anthropic SDK (imported lazily)."""

    def __init__(self, model: str = ENRICH_MODEL):
        import anthropic  # noqa: PLC0415 — optional dep, only needed for --deep

        self._client = anthropic.Anthropic()
        self._model = model

    def judge(self, prompt: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def _prompt_for(finding: dict) -> str:
    return (
        "You are auditing Claude Code token usage. Given this deterministic "
        "finding, give ONE or TWO sentences of concrete, specific advice or a "
        "confidence judgment. Be terse and practical.\n\n"
        f"Finding: {finding['title']}\n"
        f"Evidence: {json.dumps(finding.get('evidence', {}))[:1200]}\n"
        f"Baseline recommendation: {finding.get('recommendation', '')}\n"
    )


def enrich(aggregates: dict, out_dir: Path, client: ModelClient | None = None) -> None:
    """Annotate deep_enrichable findings in-place; write deep/enrichment.json."""
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            aggregates["deep_skipped"] = "no ANTHROPIC_API_KEY; deep pass skipped"
            return
        client = AnthropicClient()

    enriched: dict[str, str] = {}
    count = 0
    for finding in aggregates.get("findings", []):
        if not finding.get("deep_enrichable") or count >= MAX_FINDINGS:
            continue
        try:
            note = client.judge(_prompt_for(finding))
        except Exception as exc:  # never let enrichment break a scan
            note = f"(enrichment failed: {exc})"
        finding["deep_note"] = note
        enriched[finding["detector_id"]] = note
        count += 1

    deep_dir = out_dir / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)
    (deep_dir / "enrichment.json").write_text(json.dumps(enriched, indent=2))
