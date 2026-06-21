"""Per-detector trigger + negative-control tests with pinned thresholds."""

from __future__ import annotations

from conftest import corpus, session, tool, turn, usage

from tokenomics.detectors.cache_busting import DETECTOR as cache_busting
from tokenomics.detectors.claudemd_bloat import DETECTOR as claudemd
from tokenomics.detectors.context_window import DETECTOR as context_window
from tokenomics.detectors.routing import DETECTOR as routing
from tokenomics.detectors.search_efficiency import DETECTOR as search
from tokenomics.detectors.second_tier import DETECTOR as second_tier
from tokenomics.model import StaticEnv

# ── D2 routing ───────────────────────────────────────────────────────────────

def test_routing_opus_everywhere_fires(cfg):
    turns = [turn(model="claude-opus-4-8", u=usage(input=1000, output=10)) for _ in range(5)]
    findings = routing.run(corpus([session(turns=turns)]), cfg)
    assert any("Opus-everywhere" in f.title for f in findings)
    assert findings[0].severity == 3


def test_routing_mixed_models_quiet(cfg):
    turns = [turn(model="claude-haiku-4-5", u=usage(input=1000, output=500)) for _ in range(5)]
    assert routing.run(corpus([session(turns=turns)]), cfg) == []


# ── D5 cache busting ─────────────────────────────────────────────────────────

def test_cache_busting_low_efficiency_fires(cfg):
    turns = [turn(u=usage(input=10, cache_creation=10000, cache_read=100)) for _ in range(3)]
    findings = cache_busting.run(corpus([session(turns=turns)]), cfg)
    assert findings and findings[0].severity >= 2


def test_cache_busting_healthy_quiet(cfg):
    turns = [turn(u=usage(input=10, cache_creation=100, cache_read=10000)) for _ in range(3)]
    assert cache_busting.run(corpus([session(turns=turns)]), cfg) == []


# ── D3 context window ────────────────────────────────────────────────────────

def test_context_peak_fires(cfg):
    turns = [turn(u=usage(input=200_000))]
    findings = context_window.run(corpus([session(turns=turns)]), cfg)
    assert any("Large context" in f.title for f in findings)


def test_context_small_quiet(cfg):
    turns = [turn(u=usage(input=5_000))]
    assert context_window.run(corpus([session(turns=turns)]), cfg) == []


def test_context_unused_mcp_flagged(cfg):
    static = StaticEnv(mcp_servers=[{"name": "notion"}, {"name": "linear"}])
    turns = [turn(u=usage(input=1000),
                  tools=[tool("mcp__notion__search", is_mcp=True, server="notion")])]
    findings = context_window.run(corpus([session(turns=turns)], static), cfg)
    unused = [f for f in findings if "never called" in f.title]
    assert unused and "linear" in unused[0].evidence["unused_mcp_servers"]


# ── D1 search efficiency ─────────────────────────────────────────────────────

def test_search_heavy_no_indexer_high(cfg):
    tools = [tool("Grep", tid=f"g{i}", inp={"pattern": f"p{i}"}) for i in range(10)]
    turns = [turn(u=usage(input=10), tools=tools)]
    findings = search.run(corpus([session(turns=turns)]), cfg)
    assert findings and findings[0].severity == 3


def test_search_heavy_with_indexer_medium(cfg):
    static = StaticEnv(plugins=[{"name": "pyright-lsp"}])
    tools = [tool("Grep", tid=f"g{i}", inp={"pattern": f"p{i}"}) for i in range(10)]
    turns = [turn(u=usage(input=10), tools=tools)]
    findings = search.run(corpus([session(turns=turns)], static), cfg)
    assert findings and findings[0].severity == 2


def test_search_light_quiet(cfg):
    turns = [turn(u=usage(input=10), tools=[tool("Read", inp={"file_path": "/a"})])]
    assert search.run(corpus([session(turns=turns)]), cfg) == []


# ── D4 CLAUDE.md ─────────────────────────────────────────────────────────────

def test_claudemd_absent_info(cfg):
    findings = claudemd.run(corpus([session()]), cfg)
    assert findings and findings[0].severity == 0


def test_claudemd_bloat_fires(cfg):
    static = StaticEnv(claude_md=[{"path": "/CLAUDE.md", "est_tokens": 5000, "lines": 400,
                                   "duplicate_headings": ["## setup"]}])
    findings = claudemd.run(corpus([session()], static), cfg)
    assert findings and findings[0].severity == 2


# ── D7 second tier ───────────────────────────────────────────────────────────

def test_reread_fires(cfg):
    tools = [tool("Read", tid=f"r{i}", inp={"file_path": "/same.py"}, result_chars=400)
             for i in range(3)]
    turns = [turn(u=usage(input=10), tools=tools)]
    findings = second_tier.run(corpus([session(turns=turns)]), cfg)
    assert any(f.detector_id == "second_tier.rereads" for f in findings)


def test_reread_with_edit_quiet(cfg):
    tools = [tool("Read", tid=f"r{i}", inp={"file_path": "/same.py"}) for i in range(3)]
    tools.append(tool("Edit", tid="e", inp={"file_path": "/same.py"}))
    turns = [turn(u=usage(input=10), tools=tools)]
    findings = second_tier.run(corpus([session(turns=turns)]), cfg)
    assert not any(f.detector_id == "second_tier.rereads" for f in findings)


def test_tool_bloat_fires(cfg):
    turns = [turn(u=usage(input=10), tools=[tool("Bash", result_chars=80_000)])]
    findings = second_tier.run(corpus([session(turns=turns)]), cfg)
    assert any(f.detector_id == "second_tier.tool_bloat" for f in findings)
