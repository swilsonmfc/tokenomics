"""tokenomics CLI: scan | report | capture | watch | reconcile.

Commands invoke deterministic analysis over Claude Code session logs and write a
``.tokenomics/`` folder into the analyzed project. ``reconcile`` is a P1 gate
helper that proves subagent tokens aren't double-counted.
"""

from __future__ import annotations

import argparse
import os
import sys

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
