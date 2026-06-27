"""Orchestrate a scan: assemble corpus, run detectors, write .tokenomics/.

This is the entrypoint behind ``tokenomics scan``. It is deterministic; the
optional ``--deep`` pass (enrich/deep.py) only annotates existing findings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .. import AGGREGATES_SCHEMA_VERSION
from ..assemble import assemble_corpus
from ..config import OUTPUT_DIRNAME, load_config
from ..detectors import run_all
from ..features import compute_features
from ..metrics import compute_metrics, reconcile_subagents, session_context_peak_avg
from ..static_analysis import collect_static
from .render import render_markdown


def _output_dir(project_path: str) -> Path:
    d = Path(project_path) / OUTPUT_DIRNAME
    (d / "raw").mkdir(parents=True, exist_ok=True)
    return d


def build_aggregates(
    project_path: str, scan_all: bool = False, log_dir: str | None = None
) -> dict:
    cfg = load_config(project_path)
    static = collect_static(project_path)
    corpus = assemble_corpus(project_path, static, scan_all=scan_all, log_dir=log_dir)
    metrics = compute_metrics(corpus)
    findings = run_all(corpus, cfg)
    recs = reconcile_subagents(corpus)
    findings.sort(key=lambda f: (-int(f.severity), -(f.est_savings_weight or 0)))

    features = compute_features(corpus, cfg)
    catalog = corpus.catalog  # loaded once in assemble_corpus
    matched = sorted({f.pattern_id for f in findings if f.pattern_id})

    ctx_summary = []
    for s in corpus.sessions:
        peak, avg = session_context_peak_avg(s)
        if peak:
            ctx_summary.append({"session": s.session_id, "peak": peak, "avg": round(avg)})
    ctx_summary.sort(key=lambda x: -x["peak"])

    return {
        "schema_version": AGGREGATES_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "project": corpus.project_path,
        "scope": "all-projects" if scan_all else "project",
        "corpus_meta": {
            "sessions": metrics.session_count,
            "subagents": metrics.subagent_count,
            "files": corpus.file_count,
            "bytes": corpus.byte_size,
            "cc_versions": sorted(corpus.cc_versions),
            "subagent_reconciliation": {
                "checked": len(recs),
                "within_tolerance": sum(1 for r in recs if r.within_tolerance),
                "unlinked": sum(1 for r in recs if not r.linked),
            },
        },
        "totals": {
            "total_tokens": metrics.total_usage.total_tokens,
            "input": metrics.total_usage.input,
            "output": metrics.total_usage.output,
            "cache_read": metrics.total_usage.cache_read,
            "cache_creation": metrics.total_usage.cache_creation,
            "cost_usd": round(metrics.total_cost_usd, 2),
            "relative_weight": round(metrics.total_weight, 2),
            "cache_efficiency": round(metrics.cache_efficiency, 4),
        },
        "by_model": metrics.by_model_tokens,
        "by_model_cost": {k: round(v, 2) for k, v in metrics.by_model_cost.items()},
        "by_plugin": metrics.by_plugin_tokens,
        "by_skill": metrics.by_skill_tokens,
        "by_project": metrics.by_project_tokens,
        "tool_histogram": metrics.tool_histogram,
        "mcp_servers_used": metrics.mcp_servers_used,
        "context_series_summary": ctx_summary[:20],
        "static_env": {
            "plugins": static.plugins,
            "skill_count": len(static.skills),
            "agent_count": len(static.agents),
            "hooks": static.hooks,
            "mcp_servers": static.mcp_servers,
            "claude_md": static.claude_md,
        },
        "findings": [f.to_dict() for f in findings],
        "trajectory_features": features.to_dict(),
        "taxonomy": {
            "catalog_size": len(catalog.patterns),
            "by_maturity": catalog.by_maturity(),
            "matched_patterns": matched,
            # Full per-pattern coverage so the report can show the library's whole
            # diagnostic surface (every check), not just the ones this corpus tripped.
            "patterns": [
                {
                    "id": p.id,
                    "category": p.category,
                    "analysis_no": p.analysis_no,
                    "engine": p.engine,
                    "scope": p.scope,
                    "polarity": p.polarity,
                    "maturity": p.maturity,
                    "title": p.title,
                    "matched": p.id in set(matched),
                }
                for p in catalog.patterns
            ],
        },
        "pricing_basis": "claude-api skill (cached 2026-06); cache read 0.1x, write 1.25x/2x",
        "unpriced_models": metrics.unpriced_models,
    }


def run_scan(
    project_path: str, deep: bool = False, scan_all: bool = False,
    log_dir: str | None = None,
) -> dict[str, str]:
    out_dir = _output_dir(project_path)
    aggregates = build_aggregates(project_path, scan_all=scan_all, log_dir=log_dir)

    if deep:
        try:
            from ..enrich.deep import enrich
            enrich(aggregates, out_dir)
        except Exception as exc:  # deep is additive; never block the scan
            aggregates["deep_error"] = str(exc)

    agg_path = out_dir / "aggregates.json"
    agg_path.write_text(json.dumps(aggregates, indent=2))

    report_path = out_dir / "report.md"
    report_path.write_text(render_markdown(aggregates))

    meta_path = out_dir / "raw" / "corpus_meta.json"
    meta_path.write_text(json.dumps(aggregates["corpus_meta"], indent=2))

    return {"aggregates": str(agg_path), "report": str(report_path)}
