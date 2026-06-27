"""Render aggregates.json → human-readable report.md (and a re-render helper)."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import OUTPUT_DIRNAME

_SEV_ICON = {3: "🔴", 2: "🟠", 1: "🟡", 0: "ℹ️"}
_CONF_ICON = {3: "🟢", 2: "🟡", 1: "⚪"}
_CONF_LABEL = {3: "high", 2: "med", 1: "low"}


def _fmt_usd_range(lo, hi, mid=None) -> str | None:
    """A `$lo–$hi` range, collapsing to a point when lo≈hi; None if unpriced."""
    if lo is None or hi is None:
        return f"${mid:,.2f}" if mid is not None else None
    if abs(hi - lo) < 0.005:
        return f"${lo:,.2f}"
    return f"${lo:,.2f}–${hi:,.2f}"
_ANALYSIS_NAMES = {
    1: "Code-context search efficiency",
    2: "Routing intelligence",
    3: "Context window management",
    4: "CLAUDE.md hygiene",
    5: "Cache-busting behavior",
    6: "Review-stage agents",
    7: "Second-tier savings",
    8: "Output verbosity",
}

# What each analysis checks for — shown even when an analysis has no findings, so
# an empty scan still documents the library's full diagnostic surface.
_ANALYSIS_CHECKS = {
    1: "search-heavy trajectories, repeated greps, an indexer installed but unused",
    2: "premium model on trivial work, premium-everywhere token share, "
       "extended thinking on trivial turns, subagents left on a premium model",
    3: "large peak/average context window, MCP servers loaded but never called",
    4: "CLAUDE.md size (re-sent every turn) and duplicate headings",
    5: "low prompt-cache efficiency and prefix-invalidating bust turns",
    6: "redundant or over-modeled review-stage subagents",
    7: "file re-reads, oversized tool results, wide subagent fan-out, server-tool waste",
    8: "verbose prose on no-tool turns",
}


def _sparkline(values: list[int]) -> str:
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    rng = hi - lo or 1
    return "".join(blocks[min(7, int((v - lo) / rng * 7))] for v in values)


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def render_markdown(agg: dict) -> str:
    t = agg["totals"]
    cm = agg["corpus_meta"]
    L: list[str] = []
    L.append("# tokenomics report")
    L.append("")
    L.append(f"_Project_: `{agg['project']}`  ")
    L.append(f"_Generated_: {agg['generated_at']}  ")
    L.append(f"_Scope_: {cm['sessions']} sessions, {cm['subagents']} subagents, "
             f"{cm['files']} files ({_fmt_int(cm['bytes'])} bytes)")
    L.append("")

    # 1. Executive summary
    L.append("## Executive summary")
    L.append("")
    L.append(f"- **Total tokens**: {_fmt_int(t['total_tokens'])}")
    cost = t.get("cost_usd") or 0.0
    L.append(f"- **Estimated cost**: ${cost:,.2f}  (relative weight {t['relative_weight']:,.2f})")
    L.append(f"- **Cache efficiency**: {t['cache_efficiency']:.0%}")
    findings = agg["findings"]
    actionable = [f for f in findings if f["severity"] >= 1 and f.get("est_savings_weight")]
    top = sorted(actionable, key=lambda f: -(f.get("est_savings_weight") or 0))[:3]
    if top:
        L.append("- **Top savings opportunities**:")
        for f in top:
            tok = f.get("est_savings_tokens")
            tail = f" (~{_fmt_int(tok)} tok)" if tok else ""
            ci = _CONF_ICON.get(f.get("confidence", 1), "⚪")
            L.append(f"  - {_SEV_ICON[f['severity']]} {f['title']}{tail} {ci}")
    # Savings summed by confidence tier — deliberately NOT one bankable total,
    # since low-confidence figures are hypotheses, not money in the bank.
    by_conf: dict[int, list[float]] = {}
    for f in findings:
        if f["severity"] < 1:
            continue
        lo, hi = f.get("est_savings_usd_lo"), f.get("est_savings_usd_hi")
        if lo is None or hi is None:
            continue
        acc = by_conf.setdefault(int(f.get("confidence", 1)), [0.0, 0.0])
        acc[0] += lo
        acc[1] += hi
    if by_conf:
        L.append("- **Estimated savings by confidence** _(ranges; not a single total)_:")
        for c in sorted(by_conf, reverse=True):
            lo, hi = by_conf[c]
            L.append(f"  - {_CONF_ICON[c]} {_CONF_LABEL[c]}: {_fmt_usd_range(lo, hi)}")
    rec = cm.get("subagent_reconciliation", {})
    if rec.get("checked"):
        L.append(f"- _Subagent token reconciliation_: "
                 f"{rec['within_tolerance']}/{rec['checked']} within tolerance")
    L.append("")

    # 2. Cost breakdown
    L.append("## Cost breakdown")
    L.append("")
    L.append("| Model | Tokens | Est. cost |")
    L.append("|---|--:|--:|")
    costs = agg.get("by_model_cost", {})
    for model, toks in agg["by_model"].items():
        c = costs.get(model)
        cstr = f"${c:,.2f}" if c is not None else "—"
        L.append(f"| `{model}` | {_fmt_int(toks)} | {cstr} |")
    L.append("")
    if agg.get("by_plugin"):
        L.append("**By plugin (attributed tokens):** " +
                 ", ".join(f"`{k}` {_fmt_int(v)}" for k, v in list(agg["by_plugin"].items())[:8]))
        L.append("")
    if agg.get("by_skill"):
        L.append("**By skill:** " +
                 ", ".join(f"`{k}` {_fmt_int(v)}" for k, v in list(agg["by_skill"].items())[:8]))
        L.append("")
    by_project = agg.get("by_project", {})
    if len(by_project) > 1:  # only meaningful for --all (cross-project) scans
        L.append("**By project (tokens):**")
        L.append("")
        L.append("| Project | Tokens |")
        L.append("|---|--:|")
        for proj, toks in list(by_project.items())[:15]:
            L.append(f"| `{proj}` | {_fmt_int(toks)} |")
        L.append("")

    # 3. Findings by analysis
    L.append("## Findings by analysis")
    L.append("")
    by_analysis: dict[int, list] = {}
    for f in findings:
        by_analysis.setdefault(f["analysis_no"], []).append(f)
    for no in sorted(_ANALYSIS_NAMES):
        L.append(f"### {no}. {_ANALYSIS_NAMES[no]}")
        L.append("")
        check = _ANALYSIS_CHECKS.get(no)
        if check:
            L.append(f"_Checks: {check}._")
            L.append("")
        items = by_analysis.get(no, [])
        if not items:
            L.append("_No findings this scan._")
            L.append("")
            continue
        for f in items:
            L.append(f"{_SEV_ICON[f['severity']]} **{f['title']}** "
                     f"_({f['severity_label']})_")
            usd = _fmt_usd_range(f.get("est_savings_usd_lo"), f.get("est_savings_usd_hi"),
                                 f.get("est_savings_usd"))
            if f.get("est_savings_tokens") or usd:
                bits = []
                if f.get("est_savings_tokens"):
                    bits.append(f"~{_fmt_int(f['est_savings_tokens'])} tok")
                if usd:
                    bits.append(usd)
                conf = _CONF_LABEL.get(int(f.get("confidence", 1)), "low")
                L.append(f"  - Est. savings: {', '.join(bits)} _({conf} confidence)_")
            if f.get("recommendation"):
                L.append(f"  - {f['recommendation']}")
            if f.get("pattern_id"):
                mat = f.get("evidence", {}).get("maturity")
                tag = f" ({mat})" if mat else ""
                L.append(f"  - 🧬 taxonomy: `{f['pattern_id']}`{tag}")
            if f.get("deep_note"):
                L.append(f"  - 🔎 _{f['deep_note']}_")
            L.append("")

    # 4. Context window profile
    L.append("## Context window profile")
    L.append("")
    cs = agg.get("context_series_summary", [])
    if cs:
        peaks = [c["peak"] for c in cs]
        L.append(f"Peak per session: `{_sparkline(peaks)}`  (max {_fmt_int(max(peaks))})")
        L.append("")
        L.append("| Session | Peak | Avg |")
        L.append("|---|--:|--:|")
        for c in cs[:10]:
            L.append(f"| `{c['session'][:12]}` | {_fmt_int(c['peak'])} | {_fmt_int(c['avg'])} |")
        L.append("")

    # 5. Static environment
    L.append("## Static environment")
    L.append("")
    se = agg["static_env"]
    L.append("- Plugins: " + (", ".join(f"`{p['name']}`" for p in se["plugins"]) or "none"))
    L.append(f"- Skills: {se['skill_count']}  ·  Agents: {se['agent_count']}  ·  "
             f"Hooks: {len(se['hooks'])}")
    mcp = se.get("mcp_servers", [])
    L.append("- MCP servers: " + (", ".join(f"`{m['name']}`" for m in mcp) or "none"))
    cmd = se.get("claude_md", [])
    if cmd:
        for d in cmd:
            L.append(f"- CLAUDE.md ({d['scope']}): ~{_fmt_int(d['est_tokens'])} tok, "
                     f"{d['lines']} lines")
    else:
        L.append("- CLAUDE.md: none found")
    L.append("")

    # 6. Taxonomy coverage
    tax = agg.get("taxonomy")
    if tax:
        L.append("## Taxonomy coverage")
        L.append("")
        mat = ", ".join(f"{k} {v}" for k, v in tax.get("by_maturity", {}).items())
        L.append(f"- Catalog: {tax.get('catalog_size', 0)} patterns ({mat or 'n/a'})")
        matched = tax.get("matched_patterns", [])
        if matched:
            L.append("- Matched this scan: " + ", ".join(f"`{m}`" for m in matched))
        else:
            L.append("- Matched this scan: none")
        L.append("")

        # Full diagnostic surface: every catalog pattern, matched or not. Shows the
        # library's breadth regardless of what this particular corpus tripped.
        patterns = tax.get("patterns", [])
        if patterns:
            n_match = sum(1 for p in patterns if p.get("matched"))
            L.append(f"**Diagnostic coverage** — {n_match}/{len(patterns)} patterns "
                     f"matched this scan:")
            L.append("")
            L.append("| Pattern | Category | Engine | Maturity | This scan |")
            L.append("|---|---|---|---|---|")
            for p in sorted(patterns, key=lambda x: (x.get("analysis_no", 0), x["id"])):
                hit = "✅ matched" if p.get("matched") else "— not matched"
                L.append(f"| `{p['id']}` | {p.get('category', '')} | "
                         f"{p.get('engine', '')} | {p.get('maturity', '')} | {hit} |")
            L.append("")

    # 7. Methodology
    L.append("## Methodology & caveats")
    L.append("")
    L.append("- Token sums use top-level `message.usage` only (never `iterations[]`).")
    L.append("- Subagent tokens are counted once from transcripts; the parent rollup is "
             "used only to cross-check linkage.")
    L.append(f"- Pricing basis: {agg.get('pricing_basis', 'n/a')}.")
    if agg.get("unpriced_models"):
        L.append(f"- Unpriced models (ranked by relative weight): "
                 f"{', '.join(agg['unpriced_models'])}.")
    L.append(f"- Claude Code versions seen: {', '.join(cm.get('cc_versions') or ['?'])}.")
    L.append("")
    return "\n".join(L)


def rerender(project_path: str) -> str | None:
    agg_path = Path(project_path) / OUTPUT_DIRNAME / "aggregates.json"
    if not agg_path.exists():
        return None
    agg = json.loads(agg_path.read_text())
    out = Path(project_path) / OUTPUT_DIRNAME / "report.md"
    out.write_text(render_markdown(agg))
    return str(out)
