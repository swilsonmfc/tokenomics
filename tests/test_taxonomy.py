"""Taxonomy substrate: feature vector, safe evaluator, catalog, matcher."""

from __future__ import annotations

import pytest
from conftest import corpus, session, subagent, tool, turn, usage

from tokenomics.detectors import run_all
from tokenomics.detectors.taxonomy_match import DETECTOR as taxonomy_match
from tokenomics.features import compute_features
from tokenomics.model import StaticEnv
from tokenomics.taxonomy import CATEGORY_ANALYSIS, load_catalog
from tokenomics.taxonomy.evaluator import RuleError, compile_rule, evaluate

# ── feature layer ────────────────────────────────────────────────────────────

def test_features_search_ratio_and_models(cfg):
    tools = [tool("Grep", tid=f"g{i}", inp={"pattern": "x"}) for i in range(3)]
    tools.append(tool("Read", tid="r", inp={"file_path": "/a"}))
    turns = [turn(model="claude-opus-4-8", u=usage(input=1000, output=10), tools=tools)]
    feats = compute_features(corpus([session(turns=turns)]), cfg)
    assert feats.total_tool_calls == 4
    assert feats.search_calls == 3
    assert feats.search_ratio == 0.75
    assert feats.repeated_search_max == 3
    assert feats.premium_token_share == 1.0
    assert feats.top_model == "claude-opus-4-8"


def test_features_thinking_trivial_and_premium_subagents(cfg):
    main = [turn(model="claude-opus-4-8", u=usage(input=500, output=10), thinking=400)]
    sub = subagent(model="claude-opus-4-8", turns=[turn(u=usage(input=100, output=50))])
    feats = compute_features(corpus([session(turns=main, subs=[sub])]), cfg)
    assert feats.thinking_trivial_turns == 1
    assert feats.premium_subagent_runs == 1
    assert feats.subagent_count == 1


def test_features_unused_mcp_and_pins(cfg):
    static = StaticEnv(
        mcp_servers=[{"name": "notion"}, {"name": "linear"}],
        agents=[{"name": "explore", "model": "claude-haiku-4-5"}, {"name": "big"}],
    )
    turns = [turn(u=usage(input=100),
                  tools=[tool("mcp__notion__x", is_mcp=True, server="notion")])]
    feats = compute_features(corpus([session(turns=turns)], static), cfg)
    assert feats.unused_mcp_count == 1  # linear loaded, never called
    assert feats.cheap_pinned_agents == 1
    assert feats.agent_count == 2


# ── safe evaluator ───────────────────────────────────────────────────────────

def test_evaluator_basic_truth():
    code = compile_rule("a >= 3 and b < 10")
    assert evaluate(code, {"a": 5, "b": 2}) is True
    assert evaluate(code, {"a": 1, "b": 2}) is False


def test_evaluator_missing_name_is_false():
    code = compile_rule("missing > 0")
    assert evaluate(code, {}) is False


def test_evaluator_rejects_dunder():
    with pytest.raises(RuleError):
        compile_rule("().__class__.__bases__")


def test_evaluator_no_builtins():
    code = compile_rule("len(x) > 0")  # len is a builtin → blocked → False
    assert evaluate(code, {"x": [1, 2]}) is False


# ── catalog ──────────────────────────────────────────────────────────────────

def test_catalog_loads_and_validates():
    cat = load_catalog()
    assert cat.patterns
    ids = [p.id for p in cat.patterns]
    assert len(ids) == len(set(ids))  # unique
    for p in cat.patterns:
        assert p.category in CATEGORY_ANALYSIS
        assert p.analysis_no >= 1
        if p.engine == "declarative":
            assert p.compiled() is not None
        if p.engine == "detector":
            assert p.detector_id


def test_catalog_detector_patterns_map_to_real_findings():
    # Every detector-engine pattern id should be stampable by a detector.
    cat = load_catalog()
    declared = {p.id for p in cat.patterns}
    for pid in ("routing.premium-everywhere", "cache.low-efficiency",
                "search.grep-heavy", "claudemd.bloat", "secondtier.file-reread"):
        assert pid in declared


# ── matcher ──────────────────────────────────────────────────────────────────

def test_matcher_thinking_on_trivial_fires(cfg):
    turns = [turn(model="claude-opus-4-8", u=usage(input=500, output=10), thinking=300)
             for _ in range(3)]
    findings = taxonomy_match.run(corpus([session(turns=turns)]), cfg)
    hit = [f for f in findings if f.pattern_id == "routing.thinking-on-trivial"]
    assert hit and hit[0].analysis_no == 2


def test_matcher_quiet_when_no_pattern(cfg):
    turns = [turn(model="claude-haiku-4-5", u=usage(input=100, output=500))]
    findings = taxonomy_match.run(corpus([session(turns=turns)]), cfg)
    assert findings == []


def test_matcher_premium_subagents_fires(cfg):
    subs = [subagent(agent_id=f"a{i}", model="claude-opus-4-8",
                     turns=[turn(u=usage(input=100, output=50))]) for i in range(2)]
    findings = taxonomy_match.run(corpus([session(turns=[turn(u=usage(input=10))], subs=subs)]),
                                  cfg)
    assert any(f.pattern_id == "routing.premium-subagents" for f in findings)


# ── linkage: detector findings carry a pattern_id ────────────────────────────

def test_detector_findings_stamp_pattern_id(cfg):
    turns = [turn(model="claude-opus-4-8", u=usage(input=1000, output=10)) for _ in range(5)]
    findings = run_all(corpus([session(turns=turns)]), cfg)
    routing = [f for f in findings if f.detector_id == "routing"]
    assert routing and routing[0].pattern_id == "routing.premium-everywhere"
