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


# ── external-corpus feature signals ──────────────────────────────────────────

def test_features_verbose_prose_and_bloat(cfg):
    prose = turn(uuid="p", u=usage(input=1000, output=700))           # no tools, big output
    big = turn(uuid="b", u=usage(input=200, output=10),
               tools=[tool("WebFetch", inp={"url": "x"}, result_chars=60_000)])
    feats = compute_features(corpus([session(turns=[prose, big])]), cfg)
    assert feats.verbose_prose_turns == 1
    assert feats.bloated_tool_results == 1


def test_features_repeated_calls_excludes_reads_and_edits(cfg):
    tools = [
        tool("Bash", tid="b1", inp={"command": "ls"}),
        tool("Bash", tid="b2", inp={"command": "ls"}),       # identical → 1 repeat
        tool("Read", tid="r1", inp={"file_path": "/a"}),
        tool("Read", tid="r2", inp={"file_path": "/a"}),     # reread, NOT a repeated-call
        tool("Edit", tid="e1", inp={"file_path": "/a"}),
        tool("Edit", tid="e2", inp={"file_path": "/a"}),     # edit twice, NOT a repeated-call
    ]
    feats = compute_features(corpus([session(turns=[turn(u=usage(input=100), tools=tools)])]), cfg)
    assert feats.repeated_tool_calls == 1


def test_features_rework_loop_counts_reedit_after_command(cfg):
    t1 = turn(uuid="t1", u=usage(input=100),
              tools=[tool("Edit", tid="e1", inp={"file_path": "/a"})])
    t2 = turn(uuid="t2", u=usage(input=100), parent="t1",
              tools=[tool("Bash", tid="b1", inp={"command": "pytest"})])
    t3 = turn(uuid="t3", u=usage(input=100), parent="t2",
              tools=[tool("Edit", tid="e2", inp={"file_path": "/a"})])      # rework
    feats = compute_features(corpus([session(turns=[t1, t2, t3])]), cfg)
    assert feats.rework_loops == 1


def test_features_input_growth_factor(cfg):
    small = turn(uuid="s", u=usage(input=1_000))
    big = turn(uuid="b", u=usage(input=10_000), parent="s")
    feats = compute_features(corpus([session(turns=[small, big])]), cfg)
    assert feats.input_growth_factor == 10.0


def test_features_static_and_version_signals(cfg):
    static = StaticEnv(
        mcp_servers=[{"name": f"s{i}"} for i in range(11)],
        claude_md=[{"lines": 250, "est_tokens": 900}],
    )
    sess = session(turns=[turn(u=usage(input=100))], cc_version="2.1.75")
    feats = compute_features(corpus([sess], static), cfg)
    assert feats.mcp_server_count == 11
    assert feats.claudemd_lines == 250
    assert feats.cc_cache_bug is True


def test_cc_version_range_boundaries():
    from tokenomics.features import cc_version_in_cache_bug_range as bug
    assert bug("2.1.69") and bug("2.1.89") and bug("2.1.75")
    assert not bug("2.1.68") and not bug("2.1.90") and not bug("2.2.0")
    assert not bug(None) and not bug("garbage")


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


# ── external-corpus patterns: matcher firing ─────────────────────────────────

def _fired(findings, pid):
    return any(f.pattern_id == pid for f in findings)


def test_matcher_cc_cache_bug_fires(cfg):
    sess = session(turns=[turn(u=usage(input=100, output=50))], cc_version="2.1.80")
    findings = taxonomy_match.run(corpus([sess]), cfg)
    assert _fired(findings, "cache.buggy-cc-version")


def test_matcher_mcp_surface_and_claudemd_lines_fire(cfg):
    static = StaticEnv(
        mcp_servers=[{"name": f"s{i}"} for i in range(12)],
        claude_md=[{"lines": 300, "est_tokens": 1000}],
    )
    findings = taxonomy_match.run(corpus([session(turns=[turn(u=usage(input=100))])], static), cfg)
    assert _fired(findings, "mcp.tool-surface-bloat")
    assert _fired(findings, "claudemd.over-line-limit")


def test_matcher_verbose_prose_fires(cfg):
    turns = [turn(uuid=f"p{i}", u=usage(input=100, output=800)) for i in range(5)]
    findings = taxonomy_match.run(corpus([session(turns=turns)]), cfg)
    assert _fired(findings, "output.verbose-prose")


def test_matcher_no_subagent_offload_fires_and_clears_with_subagent(cfg):
    big = [turn(u=usage(input=200_000, output=10))]                 # ctx_peak ≥ 150k
    findings = taxonomy_match.run(corpus([session(turns=big)]), cfg)
    assert _fired(findings, "context.no-subagent-offload")
    # add a subagent → cause removed → pattern must not fire
    with_sub = session(turns=big, subs=[subagent(turns=[turn(u=usage(input=50))])])
    findings2 = taxonomy_match.run(corpus([with_sub]), cfg)
    assert not _fired(findings2, "context.no-subagent-offload")


def test_matcher_runaway_history_fires(cfg):
    grow = [turn(uuid="a", u=usage(input=2_000)),
            turn(uuid="b", u=usage(input=20_000), parent="a")]       # 10x growth ≥ 5x
    findings = taxonomy_match.run(corpus([session(turns=grow)]), cfg)
    assert _fired(findings, "context.runaway-history")


def test_matcher_rework_and_repeated_calls_fire(cfg):
    # two rework cycles + two identical Bash repeats
    tools = []
    for i in range(3):  # edit, run, edit, run, edit → 2 rework loops
        tools.append(tool("Edit", tid=f"e{i}", inp={"file_path": "/a"}))
        tools.append(tool("Bash", tid=f"r{i}", inp={"command": "pytest"}))
    findings = taxonomy_match.run(
        corpus([session(turns=[turn(u=usage(input=100), tools=tools)])]), cfg)
    assert _fired(findings, "workflow.rework-loop")
    # "pytest" Bash issued 3× → 2 repeats ≥ threshold 3? no — craft explicit repeats
    rep = [tool("Bash", tid=f"x{i}", inp={"command": "make build"}) for i in range(4)]
    findings2 = taxonomy_match.run(
        corpus([session(turns=[turn(u=usage(input=100), tools=rep)])]), cfg)
    assert _fired(findings2, "tooling.repeated-tool-calls")


def test_matcher_noisy_tool_output_fires(cfg):
    tools = [tool("Bash", tid=f"b{i}", inp={"command": f"cmd{i}"}, result_chars=60_000)
             for i in range(3)]
    findings = taxonomy_match.run(
        corpus([session(turns=[turn(u=usage(input=100), tools=tools)])]), cfg)
    assert _fired(findings, "tooling.noisy-tool-output")


def test_matcher_session_sprawl_fires(cfg):
    turns = [turn(uuid=f"t{i}", u=usage(input=100, output=50)) for i in range(130)]
    findings = taxonomy_match.run(corpus([session(turns=turns)]), cfg)
    assert _fired(findings, "context.session-sprawl")


def test_matcher_repeated_grep_fires(cfg):
    tools = [tool("Grep", tid=f"g{i}", inp={"pattern": "needle"}) for i in range(3)]
    findings = taxonomy_match.run(
        corpus([session(turns=[turn(u=usage(input=100), tools=tools)])]), cfg)
    assert _fired(findings, "search.repeated-grep")


def test_matcher_external_patterns_quiet_on_clean_session(cfg):
    # a small, well-behaved session fires none of the new anti-patterns
    clean = session(turns=[turn(model="claude-haiku-4-5", u=usage(input=500, output=100),
                                tools=[tool("Read", inp={"file_path": "/a"})])],
                    cc_version="2.2.0")
    findings = taxonomy_match.run(corpus([clean]), cfg)
    new_ids = {"search.repeated-grep", "context.no-subagent-offload", "context.session-sprawl",
               "context.runaway-history", "claudemd.over-line-limit", "cache.buggy-cc-version",
               "mcp.tool-surface-bloat", "tooling.noisy-tool-output",
               "tooling.repeated-tool-calls", "workflow.rework-loop", "output.verbose-prose"}
    assert not (new_ids & {f.pattern_id for f in findings})


# ── linkage: detector findings carry a pattern_id ────────────────────────────

def test_detector_findings_stamp_pattern_id(cfg):
    turns = [turn(model="claude-opus-4-8", u=usage(input=1000, output=10)) for _ in range(5)]
    findings = run_all(corpus([session(turns=turns)]), cfg)
    routing = [f for f in findings if f.detector_id == "routing"]
    assert routing and routing[0].pattern_id == "routing.premium-everywhere"
