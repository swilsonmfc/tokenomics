"""tokenomics CLI: scan | report | mine | promote | capture | watch | reconcile.

Commands invoke deterministic analysis over Claude Code session logs and write a
``.tokenomics/`` folder into the analyzed project. ``reconcile`` is a P1 gate
helper that proves subagent tokens aren't double-counted. ``mine`` is the
empirical pass that harvests candidate patterns from the corpus.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__


def _default_project() -> str:
    return os.getcwd()


def cmd_scan(args: argparse.Namespace) -> int:
    from .report.aggregate import run_scan

    paths = run_scan(args.project, deep=args.deep, scan_all=args.all)
    scope = "all projects" if args.all else args.project
    print(f"tokenomics scan complete ({scope}) → {paths['report']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report.render import rerender

    out = rerender(args.project)
    if out is None:
        print("No aggregates.json found — run `tokenomics scan` first.", file=sys.stderr)
        return 1
    print(f"Re-rendered report → {out}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from .capture.runner import dispatch

    return dispatch(args.event)


def cmd_watch(args: argparse.Namespace) -> int:
    from .capture.runner import set_enabled

    set_enabled(args.project, args.state == "on")
    print(f"tokenomics capture {'enabled' if args.state == 'on' else 'disabled'}")
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    import json
    from datetime import UTC, datetime

    from .assemble import assemble_corpus
    from .config import OUTPUT_DIRNAME, load_config
    from .miner import mine
    from .report.mine_render import render_mine_markdown
    from .static_analysis import collect_static
    from .taxonomy import PROJECT_CATALOG_SUBDIR, dump_patterns_toml

    cfg = load_config(args.project)
    static = collect_static(args.project)
    corpus = assemble_corpus(args.project, static, scan_all=args.all)
    today = datetime.now(UTC).date().isoformat()
    report = mine(corpus, cfg, today=today)

    out_dir = Path(args.project) / OUTPUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mined.json").write_text(json.dumps(report.to_dict(), indent=2))
    md = render_mine_markdown(report.to_dict(), corpus.project_path,
                              datetime.now(UTC).isoformat())
    (out_dir / "mined-report.md").write_text(md)

    patterns = report.patterns()
    if patterns:
        tax_dir = Path(args.project) / PROJECT_CATALOG_SUBDIR
        tax_dir.mkdir(parents=True, exist_ok=True)
        header = (f"Mined candidate patterns ({today}). Correlational — confirm with "
                  "`tokenomics promote` (stability + separation gated) before trusting.")
        (tax_dir / "mined.toml").write_text(dump_patterns_toml(patterns, header))

    if not report.mined:
        print(f"tokenomics mine: {report.reason}")
    else:
        print(f"tokenomics mine: {len(patterns)} candidate pattern(s) from "
              f"{report.included_count} sessions → {out_dir / 'mined-report.md'}")
        print("  promote qualifying ones with `tokenomics promote --all-qualifying`")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from .assemble import assemble_corpus
    from .config import load_config
    from .promote import promote_candidates
    from .static_analysis import collect_static

    cfg = load_config(args.project)
    static = collect_static(args.project)
    corpus = assemble_corpus(args.project, static, scan_all=args.all)
    today = datetime.now(UTC).date().isoformat()
    ids = None if args.all_qualifying else (args.pattern or None)
    if not args.all_qualifying and not args.pattern:
        print("tokenomics promote: name pattern id(s) or pass --all-qualifying",
              file=sys.stderr)
        return 1

    res = promote_candidates(args.project, cfg, corpus, pattern_ids=ids, today=today)
    if res.reason:
        print(f"tokenomics promote: {res.reason}")
        return 1
    for p in res.promoted:
        print(f"  ✓ promoted {p.id}  ({p.rule})")
    for pid, why in res.skipped:
        print(f"  – skipped {pid}: {why}")
    print(f"tokenomics promote: {len(res.promoted)} promoted, {len(res.skipped)} skipped")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    from .assemble import assemble_corpus
    from .metrics import compute_metrics, reconcile_subagents

    corpus = assemble_corpus(args.project, scan_all=args.all)
    m = compute_metrics(corpus)
    print(f"Project: {corpus.project_path}")
    print(f"Sessions: {m.session_count}  Subagents: {m.subagent_count}  "
          f"Files: {corpus.file_count}  Bytes: {corpus.byte_size:,}")
    print(f"Total tokens: {m.total_usage.total_tokens:,}  "
          f"Est. cost: ${m.total_cost_usd:,.2f}  Weight: {m.total_weight:,.2f}")
    print(f"Cache efficiency: {m.cache_efficiency:.1%}")
    print(f"By model (tokens): {m.by_model_tokens}")
    if m.unpriced_models:
        print(f"Unpriced models: {m.unpriced_models}")
    recs = reconcile_subagents(corpus)
    bad = [r for r in recs if not r.within_tolerance]
    print(f"Subagent reconciliation: {len(recs) - len(bad)}/{len(recs)} within tolerance "
          f"(final-turn usage vs rollup totalTokens)")
    for r in bad[:10]:
        print(f"  MISMATCH {r.agent_id}: last_turn={r.last_turn_tokens} "
              f"rollup={r.rollup_tokens} delta={r.delta} (full_transcript={r.transcript_total})")
    return 0 if not bad else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tokenomics", description=__doc__)
    p.add_argument("--version", action="version", version=f"tokenomics {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scan", help="analyze logs + static config, write .tokenomics/ report")
    sp.add_argument("--project", default=_default_project(),
                    help="project to scan (default: current directory)")
    sp.add_argument("--all", action="store_true",
                    help="scan ALL projects under ~/.claude/projects, not just this one")
    sp.add_argument("--deep", action="store_true", help="LLM enrichment pass (semantic findings)")
    sp.set_defaults(func=cmd_scan)

    rp = sub.add_parser("report", help="re-render report.md from cached aggregates.json")
    rp.add_argument("--project", default=_default_project())
    rp.set_defaults(func=cmd_report)

    mp = sub.add_parser("mine", help="harvest candidate cost patterns from the corpus")
    mp.add_argument("--project", default=_default_project())
    mp.add_argument("--all", action="store_true",
                    help="pool sessions across all projects (recommended — more data)")
    mp.set_defaults(func=cmd_mine)

    pp = sub.add_parser("promote",
                        help="promote qualifying mined candidates to empirical patterns")
    pp.add_argument("--project", default=_default_project())
    pp.add_argument("--all", action="store_true",
                    help="pool sessions across all projects for the stability re-mine")
    pp.add_argument("--all-qualifying", action="store_true",
                    help="promote every candidate that passes the gate")
    pp.add_argument("pattern", nargs="*", help="specific candidate pattern id(s) to promote")
    pp.set_defaults(func=cmd_promote)

    cp = sub.add_parser("capture", help="capture-mode hook entrypoint (reads event JSON on stdin)")
    cp.add_argument("event", choices=["session-start", "prompt-submit", "post-tool", "stop"])
    cp.set_defaults(func=cmd_capture)

    wp = sub.add_parser("watch", help="toggle capture mode")
    wp.add_argument("state", choices=["on", "off"])
    wp.add_argument("--project", default=_default_project())
    wp.set_defaults(func=cmd_watch)

    xp = sub.add_parser("reconcile", help="P1 gate: print totals + subagent token reconciliation")
    xp.add_argument("--project", default=_default_project())
    xp.add_argument("--all", action="store_true", help="reconcile across all projects")
    xp.set_defaults(func=cmd_reconcile)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
