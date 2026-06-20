"""Capture: incremental offset advances, flags fire once, runner exits 0."""

from __future__ import annotations

import json

from conftest import rec_assistant

from tokenomics.capture.flags import evaluate_records
from tokenomics.capture.runner import dispatch, set_enabled
from tokenomics.capture.tailer import read_new_records
from tokenomics.config import Config


def _append(path, records):
    with path.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_offset_advances_incrementally(tmp_path):
    log = tmp_path / "s1.jsonl"
    log.write_text("")
    _append(log, [rec_assistant("u1", usage_dict={"input_tokens": 1})])
    first = read_new_records(tmp_path, "s1", log)
    assert len(first) == 1
    # No new lines → nothing returned.
    assert read_new_records(tmp_path, "s1", log) == []
    _append(log, [rec_assistant("u2", usage_dict={"input_tokens": 1})])
    second = read_new_records(tmp_path, "s1", log)
    assert len(second) == 1 and second[0]["uuid"] == "u2"


def test_context_peak_flag_fires(tmp_path):
    cfg = Config()
    recs = [rec_assistant("u1", usage_dict={"input_tokens": 200_000})]
    warnings = evaluate_records(tmp_path, "s1", recs, cfg, {})
    assert any("context window" in w for w in warnings)
    cap = (tmp_path / ".tokenomics" / "capture.jsonl").read_text()
    assert "context_peak" in cap


def test_cache_bust_flag(tmp_path):
    cfg = Config()
    recs = [rec_assistant("u1", usage_dict={
        "input_tokens": 10, "cache_creation_input_tokens": 10000,
        "cache_read_input_tokens": 100})]
    warnings = evaluate_records(tmp_path, "s1", recs, cfg, {})
    assert any("cache bust" in w for w in warnings)


def test_dispatch_exits_zero_on_garbage(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakeStdin("not json"))
    assert dispatch("prompt-submit") == 0


def test_dispatch_session_start(tmp_path, monkeypatch):
    payload = json.dumps({"session_id": "s1", "cwd": str(tmp_path)})
    monkeypatch.setattr("sys.stdin", _FakeStdin(payload))
    assert dispatch("session-start") == 0
    assert (tmp_path / ".tokenomics" / "capture.jsonl").exists()


def test_watch_toggle(tmp_path):
    set_enabled(str(tmp_path), False)
    text = (tmp_path / ".tokenomics" / "config.toml").read_text()
    assert "capture_enabled = false" in text
    set_enabled(str(tmp_path), True)
    text = (tmp_path / ".tokenomics" / "config.toml").read_text()
    assert "capture_enabled = true" in text
    assert text.count("capture_enabled") == 1  # no duplicate keys


class _FakeStdin:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data
