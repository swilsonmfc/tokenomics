"""Savings primitive + confidence-aware, avoidable-volume-scoped detector output."""

from __future__ import annotations

from conftest import corpus, session, subagent, tool, turn, usage

from tokenomics import pricing
from tokenomics.detectors.base import Confidence
from tokenomics.detectors.cache_busting import DETECTOR as cache_busting
from tokenomics.detectors.review_agents import DETECTOR as review_agents
from tokenomics.detectors.routing import DETECTOR as routing
from tokenomics.detectors.second_tier import DETECTOR as second_tier

OPUS = "claude-opus-4-8"  # $5/Mtok input, $25 output


# ── estimate_savings primitive ───────────────────────────────────────────────

def test_estimate_savings_input_priced_golden():
    s = pricing.estimate_savings(1_000_000, OPUS, kind="input", frac=(1.0, 1.0),
                                 confidence=Confidence.HIGH)
    assert s["est_savings_tokens"] == 1_000_000
    assert s["est_savings_usd"] == 5.0
    assert s["est_savings_usd_lo"] == s["est_savings_usd_hi"] == 5.0
    assert abs(s["est_savings_weight"] - 5.0) < 1e-9
    assert s["confidence"] == Confidence.HIGH


def test_estimate_savings_range_from_frac():
    s = pricing.estimate_savings(1_000_000, OPUS, kind="input", frac=(0.5, 1.0),
                                 confidence=Confidence.LOW)
    assert s["est_savings_usd_lo"] == 2.5
    assert s["est_savings_usd_hi"] == 5.0
    assert s["est_savings_usd"] == 3.75
    assert s["est_savings_tokens"] == 750_000  # midpoint frac applied to volume


def test_estimate_savings_cache_premium_rate():
    # premium = (write_5m 1.25 − read 0.10) × input = 1.15 × $5 = $5.75/Mtok
    s = pricing.estimate_savings(1_000_000, OPUS, kind="cache_premium", frac=(1.0, 1.0),
                                 confidence=Confidence.MED)
    assert abs(s["est_savings_usd"] - 5.75) < 1e-6


def test_estimate_savings_unpriced_has_weight_but_no_usd():
    s = pricing.estimate_savings(1_000_000, "some-unknown-model", kind="input",
                                 frac=(1.0, 1.0), confidence=Confidence.LOW)
    assert s["est_savings_usd"] is None
    assert s["est_savings_weight"] > 0  # still ranks


# ── cache busting: scope to busted volume, not all cache creation ─────────────

def test_cache_busting_scopes_to_bust_turns(cfg):
    # 3 bust turns × 10k creation = 30k busted; savings must be a fraction of THAT,
    # never the old `total_create`-as-waste, and priced at the write/read premium.
    turns = [turn(u=usage(input=10, cache_creation=10_000, cache_read=100)) for _ in range(3)]
    f = cache_busting.run(corpus([session(turns=turns)]), cfg)[0]
    assert f.confidence == Confidence.MED
    assert 0 < f.est_savings_tokens < 30_000   # frac-scaled, not 100% of creation
    assert f.est_savings_usd and f.est_savings_usd > 0


# ── routing: firm price delta, HIGH confidence, collapsed range ───────────────

def test_routing_savings_high_confidence_point_range(cfg):
    turns = [turn(model=OPUS, u=usage(input=1000, output=10)) for _ in range(5)]
    f = routing.run(corpus([session(turns=turns)]), cfg)[0]
    assert f.confidence == Confidence.HIGH
    assert f.est_savings_usd_lo == f.est_savings_usd_hi  # firm delta, not a range
    assert f.est_savings_usd and f.est_savings_usd > 0


# ── review agents: duplicate runs = avoidable tokens; over-model = price delta ─

def test_review_redundant_runs_scoped(cfg):
    # Two same-type reviews in one session → the 2nd is the avoidable duplicate.
    sub_turns = [turn(model="claude-sonnet-4-6", u=usage(input=0, output=4000))]
    subs = [subagent(agent_id="r1", agent_type="code-reviewer", turns=sub_turns,
                     model="claude-sonnet-4-6"),
            subagent(agent_id="r2", agent_type="code-reviewer", turns=sub_turns,
                     model="claude-sonnet-4-6")]
    f = review_agents.run(corpus([session(subs=subs)]), cfg)[0]
    assert f.evidence["duplicate_run_count"] == 1
    assert f.confidence == Confidence.MED
    # Only the duplicate's tokens count as avoidable, not all review volume.
    assert f.est_savings_tokens and f.est_savings_tokens <= 4000
    assert f.est_savings_usd and f.est_savings_usd > 0


def test_review_single_run_quiet_savings(cfg):
    sub_turns = [turn(model="claude-sonnet-4-6", u=usage(output=4000))]
    subs = [subagent(agent_id="r1", agent_type="code-reviewer", turns=sub_turns,
                     model="claude-sonnet-4-6")]
    f = review_agents.run(corpus([session(subs=subs)]), cfg)[0]
    assert f.severity == 0  # INFO: not redundant, not over-modeled
    assert f.est_savings_tokens is None


# ── second tier: re-reads scoped past the first read, fan-out now priced ──────

def test_reread_savings_excludes_first_read(cfg):
    # 4 reads of one 400-char file: only 3/4 of the volume is avoidable.
    tools = [tool("Read", tid=f"r{i}", inp={"file_path": "/same.py"}, result_chars=400)
             for i in range(4)]
    turns = [turn(u=usage(input=10), tools=tools)]
    findings = second_tier.run(corpus([session(turns=turns)]), cfg)
    rr = next(f for f in findings if f.detector_id == "second_tier.rereads")
    assert rr.confidence == Confidence.MED
    assert rr.est_savings_tokens and rr.est_savings_tokens > 0


def test_fanout_now_carries_savings(cfg):
    spawns = [tool("Task", tid=f"a{i}", spawned=f"agent{i}") for i in range(8)]
    turns = [turn(model=OPUS, u=usage(input=1000), tools=spawns)]
    findings = second_tier.run(corpus([session(turns=turns)]), cfg)
    fo = next(f for f in findings if f.detector_id == "second_tier.fanout")
    assert fo.est_savings_weight > 0  # previously emitted no savings → invisible
