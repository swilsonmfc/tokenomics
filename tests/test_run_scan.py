"""End-to-end orchestration: run_scan over a fixtured log dir writes the report."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import rec_assistant, write_jsonl

from tokenomics.config import namespaced_dir
from tokenomics.report.aggregate import run_scan


def test_run_scan_end_to_end(tmp_path, monkeypatch):
    # Point the log-discovery root at a fixtured projects dir.
    projects = tmp_path / "projects"
    monkeypatch.setattr("tokenomics.logpath.PROJECTS_DIR", projects)

    project = tmp_path / "proj"
    project.mkdir()
    log_dir = projects / namespaced_dir(project)
    write_jsonl(log_dir / "s1.jsonl", [
        rec_assistant("u1", usage_dict={
            "input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 200}),
    ])

    paths = run_scan(str(project))

    agg = json.loads(Path(paths["aggregates"]).read_text())
    assert agg["corpus_meta"]["sessions"] == 1
    assert agg["totals"]["total_tokens"] == 1250  # 1000 + 50 + 200
    assert agg["totals"]["cost_usd"] > 0
    # taxonomy summary comes from the corpus-loaded catalog (no detector I/O).
    assert agg["taxonomy"]["catalog_size"] > 0

    report = Path(paths["report"]).read_text()
    assert "Executive summary" in report
    assert (project / ".tokenomics" / "aggregates.json").exists()


def test_run_scan_empty_corpus_is_clean(tmp_path, monkeypatch):
    # No logs at all → orchestration still produces a valid (zeroed) report.
    monkeypatch.setattr("tokenomics.logpath.PROJECTS_DIR", tmp_path / "projects")
    project = tmp_path / "proj"
    project.mkdir()
    paths = run_scan(str(project))
    agg = json.loads(Path(paths["aggregates"]).read_text())
    assert agg["corpus_meta"]["sessions"] == 0
    assert agg["totals"]["total_tokens"] == 0
    assert Path(paths["report"]).exists()
