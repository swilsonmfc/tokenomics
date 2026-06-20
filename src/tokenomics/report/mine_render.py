"""Render a MineReport dict → human-readable mined-report.md."""

from __future__ import annotations


def _fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def render_mine_markdown(rep: dict, project: str, generated_at: str) -> str:
    L: list[str] = []
    L.append("# tokenomics — mined patterns (empirical)")
    L.append("")
    L.append(f"_Project_: `{project}`  ")
    L.append(f"_Generated_: {generated_at}  ")
    L.append(f"_Outcome metric_: {rep.get('outcome_name', 'n/a')} (higher = worse)")
    L.append("")

    if not rep.get("mined"):
        L.append("## Not enough data")
        L.append("")
        L.append(f"Mining was skipped: {rep.get('reason', 'unknown')}.")
        L.append("")
        L.append("Mining contrasts your expensive vs cheap sessions, so it needs a corpus. "
                 "Try `tokenomics mine --all` to pool sessions across all projects.")
        L.append("")
        return "\n".join(L)

    L.append(f"Analyzed {rep['included_count']} of {rep['session_count']} sessions "
             f"(rest had too little output to score). Expensive cohort = top quartile "
             f"(outcome ≥ {rep['expensive_boundary']:g}); cheap = bottom quartile "
             f"(≤ {rep['cheap_boundary']:g}).")
    L.append("")

    L.append("## Candidate patterns")
    L.append("")
    findings = rep.get("findings", [])
    if not findings:
        L.append("_No signal separated the cohorts above threshold._ Either spend is "
                 "uniform or the corpus is too small to be conclusive.")
        L.append("")
    else:
        L.append("Correlational — confirm with `tokenomics promote` before trusting. Each is "
                 "written to `.tokenomics/taxonomy/mined.toml` as `maturity = candidate`.")
        L.append("")
        L.append("| Signal | Expensive (median) | Cheap (median) | Separation | Suggested rule |")
        L.append("|---|--:|--:|--:|---|")
        for f in findings:
            L.append(f"| {f['label']} (`{f['feature']}`) | {f['bad_median']:g} | "
                     f"{f['good_median']:g} | {f['separation']:.2f} | `{f['rule']}` |")
        L.append("")
        for f in findings:
            L.append(f"- 🧬 `{f['pattern_id']}` _({f['severity']}, candidate)_ — "
                     f"expensive sessions run **{f['label']}** at a median of "
                     f"{f['bad_median']:g} vs {f['good_median']:g} in cheap ones.")
        L.append("")

    L.append("## Session benchmark (most cost-intensive first)")
    L.append("")
    L.append("| Session | Outcome | Percentile | Top model |")
    L.append("|---|--:|--:|---|")
    for b in rep.get("benchmark", []):
        L.append(f"| `{b['session'][:12]}` | {b['outcome']:g} | {b['percentile']}th | "
                 f"`{b.get('top_model') or '?'}` |")
    L.append("")

    L.append("## How to act")
    L.append("")
    L.append("- Promote qualifying candidates with `tokenomics promote --all-qualifying` "
             "(stability + separation gated) — they become `empirical` and fire by default.")
    L.append("- To preview candidates as findings before promoting, set "
             "`match_candidate_patterns = true` in `.tokenomics/config.toml`.")
    L.append("")
    return "\n".join(L)
