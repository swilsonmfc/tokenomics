"""Metrics: golden totals, cost, no-double-count, reconciliation."""

from __future__ import annotations

from conftest import corpus, session, subagent, turn, usage

from tokenomics.metrics import (
    compute_metrics,
    reconcile_subagents,
    session_total_usage,
    subagent_usage,
)
from tokenomics.pricing import normalize_model, usage_cost_usd


def test_normalize_model():
    assert normalize_model("claude-opus-4-8[1m]") == "claude-opus-4-8"
    assert normalize_model("us.anthropic.claude-opus-4-8") == "claude-opus-4-8"
    assert normalize_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5"


def test_opus_cost():
    # 1M input + 1M output on opus = $5 + $25 = $30.
    c = usage_cost_usd(usage(input=1_000_000, output=1_000_000), "claude-opus-4-8")
    assert abs(c - 30.0) < 1e-6


def test_cache_read_cheaper():
    c = usage_cost_usd(usage(cache_read=1_000_000), "claude-opus-4-8")
    assert abs(c - 0.5) < 1e-6  # 0.1 x $5


def test_subagent_counted_once():
    sub_turns = [turn(u=usage(input=10, output=20)), turn(u=usage(input=5, output=5))]
    sub = subagent(turns=sub_turns)
    main = [turn(u=usage(input=100, output=100))]
    s = session(turns=main, subs=[sub])
    total = session_total_usage(s)
    # main(200) + subagent transcript(40) = 240; rollup never added.
    assert total.total_tokens == 240
    assert subagent_usage(sub).total_tokens == 40


def test_reconciliation_uses_last_turn():
    sub_turns = [turn(u=usage(input=10, cache_read=100)),     # 110
                 turn(u=usage(input=5, output=5, cache_read=40))]  # final = 50
    sub = subagent(turns=sub_turns, rollup_total=50)
    c = corpus([session(subs=[sub])])
    recs = reconcile_subagents(c)
    assert recs[0].within_tolerance
    assert recs[0].last_turn_tokens == 50
    assert recs[0].transcript_total == 160


def test_attribution_breakdown():
    s = session(turns=[
        turn(u=usage(input=100), plugin="myplugin", skill="myplugin:foo"),
        turn(u=usage(input=50), plugin="myplugin"),
    ])
    m = compute_metrics(corpus([s]))
    assert m.by_plugin_tokens["myplugin"] == 150
    assert m.by_skill_tokens["myplugin:foo"] == 100


def test_zero_token_turns_dont_pollute_unpriced():
    s = session(turns=[turn(model="<synthetic>", u=usage())])  # 0 tokens
    m = compute_metrics(corpus([s]))
    assert "<synthetic>" not in m.unpriced_models


def test_by_project_breakdown():
    sa = session(sid="a", project="/proj/a", turns=[turn(u=usage(input=100))])
    sb = session(sid="b", project="/proj/b", turns=[turn(u=usage(input=300))])
    m = compute_metrics(corpus([sa, sb]))
    assert m.by_project_tokens == {"/proj/b": 300, "/proj/a": 100}  # sorted desc
