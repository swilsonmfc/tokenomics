"""Empirical miner (Phase B): cohorts, discrimination, persistence, gating."""

from __future__ import annotations

from dataclasses import replace

from conftest import corpus, session, tool, turn, usage

from tokenomics.config import Config
from tokenomics.detectors.taxonomy_match import DETECTOR as taxonomy_match
from tokenomics.features import compute_session_features
from tokenomics.miner import mine
from tokenomics.taxonomy import dump_patterns_toml, load_catalog


def _grep_turn(uid, n_search, model="claude-opus-4-8", out=300):
    tools = [tool("Grep", tid=f"{uid}g{i}", inp={"pattern": f"p{i}"}) for i in range(n_search)]
    tools.append(tool("Read", tid=f"{uid}r", inp={"file_path": "/a"}))
    return turn(uuid=uid, model=model, u=usage(input=20000, output=out), tools=tools)


def _cheap_session(sid):
    # Lots of output for the tokens, little searching → low cost intensity.
    return session(sid=sid, turns=[turn(uuid=f"{sid}t", model="claude-haiku-4-5",
                                        u=usage(input=200, output=4000),
                                        tools=[tool("Read", inp={"file_path": "/a"})])])


def _expensive_session(sid):
    # Big premium input, little output, heavy grep → high cost intensity + high search_ratio.
    return session(sid=sid, turns=[_grep_turn(f"{sid}t", n_search=9, out=300)])


# ── per-session features ─────────────────────────────────────────────────────

def test_session_features_isolated(cfg):
    s = _expensive_session("s1")
    f = compute_session_features(s, corpus().static, cfg)
    assert f.search_calls == 9
    assert f.output_tokens == 300
    assert f.weight > 0


# ── mining ───────────────────────────────────────────────────────────────────

def test_mine_skips_small_corpus(cfg):
    rep = mine(corpus([_cheap_session("a"), _expensive_session("b")]), cfg)
    assert rep.mined is False
    assert "sessions" in rep.reason


def test_mine_finds_discriminating_signal(cfg):
    sessions = [_cheap_session(f"c{i}") for i in range(6)]
    sessions += [_expensive_session(f"e{i}") for i in range(6)]
    rep = mine(corpus(sessions), cfg, today="2026-06-20")
    assert rep.mined is True
    feats = {f.feature for f in rep.findings}
    assert "search_ratio" in feats  # grep-heavy expensive cohort
    sr = next(f for f in rep.findings if f.feature == "search_ratio")
    assert sr.bad_median > sr.good_median
    assert sr.pattern.maturity == "candidate"
    assert sr.pattern.rule.startswith("search_ratio >=")
    assert sr.pattern.reviewed == "2026-06-20"


def test_mine_quiet_when_uniform(cfg):
    # All sessions identical → no signal separates cohorts.
    sessions = [_cheap_session(f"u{i}") for i in range(12)]
    rep = mine(corpus(sessions), cfg)
    assert rep.mined is True
    assert rep.findings == []


def test_mine_benchmark_ranks_expensive_first(cfg):
    sessions = [_cheap_session(f"c{i}") for i in range(6)]
    sessions += [_expensive_session(f"e{i}") for i in range(6)]
    rep = mine(corpus(sessions), cfg)
    assert rep.benchmark
    # most cost-intensive first → an expensive session leads
    assert rep.benchmark[0]["session"].startswith("e")


# ── persistence round-trip ───────────────────────────────────────────────────

def test_mined_patterns_round_trip(tmp_path, cfg):
    sessions = [_cheap_session(f"c{i}") for i in range(6)]
    sessions += [_expensive_session(f"e{i}") for i in range(6)]
    rep = mine(corpus(sessions), cfg, today="2026-06-20")
    toml_dir = tmp_path / ".tokenomics" / "taxonomy"
    toml_dir.mkdir(parents=True)
    (toml_dir / "mined.toml").write_text(dump_patterns_toml(rep.patterns(), "mined"))
    cat = load_catalog(project_path=tmp_path)
    ids = cat.by_id()
    assert "mined.search_ratio" in ids
    assert ids["mined.search_ratio"].maturity == "candidate"
    assert ids["mined.search_ratio"].compiled() is not None  # rule still valid


# ── candidate gating in the matcher ──────────────────────────────────────────

def test_matcher_ignores_candidates_by_default(tmp_path):
    sessions = [_cheap_session(f"c{i}") for i in range(6)]
    sessions += [_expensive_session(f"e{i}") for i in range(6)]
    cfg = Config()
    rep = mine(corpus(sessions), cfg, today="2026-06-20")
    toml_dir = tmp_path / ".tokenomics" / "taxonomy"
    toml_dir.mkdir(parents=True)
    (toml_dir / "mined.toml").write_text(dump_patterns_toml(rep.patterns()))

    c = corpus(sessions)
    c.project_path = str(tmp_path)
    default = taxonomy_match.run(c, cfg)
    assert not any((f.pattern_id or "").startswith("mined.") for f in default)

    opted_in = taxonomy_match.run(c, replace(cfg, match_candidate_patterns=True))
    assert any((f.pattern_id or "").startswith("mined.") for f in opted_in)
