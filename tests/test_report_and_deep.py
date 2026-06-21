"""Report rendering + --deep enrichment with a stubbed model client."""

from __future__ import annotations

import json

from tokenomics.enrich.deep import enrich
from tokenomics.report.render import render_markdown


def _minimal_agg(findings=None):
    return {
        "schema_version": 1,
        "generated_at": "2026-06-01T00:00:00+00:00",
        "project": "/tmp/proj",
        "corpus_meta": {"sessions": 1, "subagents": 0, "files": 1, "bytes": 100,
                        "cc_versions": ["2.1.183"],
                        "subagent_reconciliation": {"checked": 0, "within_tolerance": 0}},
        "totals": {"total_tokens": 1000, "input": 500, "output": 200, "cache_read": 300,
                   "cache_creation": 0, "cost_usd": 0.01, "relative_weight": 0.02,
                   "cache_efficiency": 1.0},
        "by_model": {"claude-opus-4-8": 1000},
        "by_model_cost": {"claude-opus-4-8": 0.01},
        "by_plugin": {}, "by_skill": {}, "tool_histogram": {}, "mcp_servers_used": {},
        "context_series_summary": [{"session": "s1", "peak": 1000, "avg": 800}],
        "static_env": {"plugins": [{"name": "pyright-lsp"}], "skill_count": 3,
                       "agent_count": 0, "hooks": [], "mcp_servers": [], "claude_md": []},
        "findings": findings or [],
        "pricing_basis": "test",
        "unpriced_models": [],
    }


def test_render_has_all_sections():
    md = render_markdown(_minimal_agg())
    for section in ["Executive summary", "Cost breakdown", "Findings by analysis",
                    "Context window profile", "Static environment", "Methodology"]:
        assert section in md


def test_render_includes_finding():
    agg = _minimal_agg(findings=[{
        "detector_id": "routing", "analysis_no": 2, "severity": 3,
        "severity_label": "HIGH", "title": "Opus-everywhere", "evidence": {},
        "est_savings_tokens": 1000, "est_savings_usd": 5.0, "est_savings_weight": 1.0,
        "recommendation": "route trivial turns", "deep_enrichable": True}])
    md = render_markdown(agg)
    assert "Opus-everywhere" in md
    assert "route trivial turns" in md


class _StubClient:
    def judge(self, prompt):
        return "stubbed note"


def test_deep_enrich_additive(tmp_path):
    agg = _minimal_agg(findings=[{
        "detector_id": "routing", "analysis_no": 2, "severity": 3,
        "severity_label": "HIGH", "title": "x", "evidence": {}, "recommendation": "",
        "deep_enrichable": True}])
    enrich(agg, tmp_path, client=_StubClient())
    assert agg["findings"][0]["deep_note"] == "stubbed note"
    data = json.loads((tmp_path / "deep" / "enrichment.json").read_text())
    assert data["routing::x"] == "stubbed note"  # keyed by detector_id + title


def test_deep_skips_non_enrichable(tmp_path):
    agg = _minimal_agg(findings=[{
        "detector_id": "x", "analysis_no": 7, "severity": 1, "severity_label": "LOW",
        "title": "x", "evidence": {}, "recommendation": "", "deep_enrichable": False}])
    enrich(agg, tmp_path, client=_StubClient())
    assert "deep_note" not in agg["findings"][0]
