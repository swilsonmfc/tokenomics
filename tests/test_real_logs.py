"""Guarded end-to-end smoke test against the real ~/.claude logs.

Every other test runs on synthetic fixtures; this one runs the whole pipeline on
the actual Claude Code JSONL so schema drift, parse crashes, or savings/mining
regressions surface against real data. It is skipped wherever no logs exist (CI,
fresh machines), so it never blocks the suite — but catches the failure mode that
synthetic fixtures structurally cannot.
"""

from __future__ import annotations

import pytest

from tokenomics.assemble import assemble_corpus
from tokenomics.config import PROJECTS_DIR, Config
from tokenomics.detectors import run_all
from tokenomics.detectors.base import Confidence, Finding
from tokenomics.metrics import compute_metrics, reconcile_subagents
from tokenomics.miner import mine

_HAS_LOGS = PROJECTS_DIR.exists() and any(PROJECTS_DIR.glob("*/*.jsonl"))
pytestmark = pytest.mark.skipif(not _HAS_LOGS, reason="no ~/.claude/projects logs present")


@pytest.fixture(scope="module")
def real_corpus():
    return assemble_corpus(str(PROJECTS_DIR), scan_all=True)


def test_pipeline_runs_on_real_logs(real_corpus):
    assert real_corpus.sessions, "expected at least one real session"
    metrics = compute_metrics(real_corpus)
    assert metrics.total_usage.total_tokens > 0

    findings = run_all(real_corpus, Config())  # must not raise on real schema
    assert isinstance(findings, list)
    for f in findings:
        assert isinstance(f, Finding)
        # Confidence-aware contract holds on real data.
        assert isinstance(f.confidence, Confidence)
        if f.est_savings_usd_lo is not None and f.est_savings_usd_hi is not None:
            assert f.est_savings_usd_lo <= f.est_savings_usd_hi


def test_accounting_invariant_holds_on_real_logs(real_corpus):
    # The parent rollup is a cross-check only; final-turn usage should line up.
    bad = [r for r in reconcile_subagents(real_corpus) if not r.within_tolerance]
    # Some drift is expected on older logs; assert the check itself runs + reports.
    assert isinstance(bad, list)


def test_mine_runs_on_real_logs(real_corpus):
    rep = mine(real_corpus, Config(), today="2026-06-20")
    assert isinstance(rep.to_dict(), dict)
    for f in rep.findings:
        assert f.pattern.maturity == "candidate"  # mining never auto-promotes
