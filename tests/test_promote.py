"""Soundness fix (per-session hit ratio) + candidate→empirical promotion gate."""

from __future__ import annotations

from dataclasses import replace

from conftest import corpus, session, tool, turn, usage

from tokenomics.config import Config
from tokenomics.detectors.taxonomy_match import DETECTOR as taxonomy_match
from tokenomics.miner import mine
from tokenomics.promote import promote_candidates
from tokenomics.taxonomy import Pattern, dump_patterns_toml, load_catalog


def _cheap(sid):
    return session(sid=sid, turns=[turn(uuid=f"{sid}t", model="claude-haiku-4-5",
                                        u=usage(input=200, output=4000),
                                        tools=[tool("Read", inp={"file_path": "/a"})])])


def _expensive(sid):
    tools = [tool("Grep", tid=f"{sid}g{i}", inp={"pattern": f"p{i}"}) for i in range(9)]
    tools.append(tool("Read", tid=f"{sid}r", inp={"file_path": "/a"}))
    return session(sid=sid, turns=[turn(uuid=f"{sid}t", model="claude-opus-4-8",
                                        u=usage(input=20000, output=300), tools=tools)])


def _mixed_corpus():
    return corpus([_cheap(f"c{i}") for i in range(6)] + [_expensive(f"e{i}") for i in range(6)])


def _write_mined(tmp_path, cfg):
    rep = mine(_mixed_corpus(), cfg, today="2026-06-20")
    d = tmp_path / ".tokenomics" / "taxonomy"
    d.mkdir(parents=True)
    (d / "mined.toml").write_text(dump_patterns_toml(rep.patterns(), "mined"))
    return d


# ── soundness: session-scoped rules judged by per-session hit ratio ───────────

def _candidate(rule):
    return Pattern(id="mined.bust_turns", category="cache", polarity="anti_pattern",
                   scope="session", engine="declarative", rule=rule,
                   signals=("bust_turns",), severity="low", maturity="candidate",
                   title="t", recommendation="r")


def _bursty_corpus(n_hit):
    # n_hit sessions have many bust turns; the rest have none.
    bust = turn(u=usage(input=10, cache_creation=10_000, cache_read=100))
    quiet = turn(u=usage(input=10, cache_read=10_000))
    sessions = [session(sid=f"h{i}", turns=[bust, bust]) for i in range(n_hit)]
    sessions += [session(sid=f"q{i}", turns=[quiet]) for i in range(12 - n_hit)]
    return corpus(sessions)


def test_session_rule_below_hit_ratio_quiet(tmp_path):
    cfg = replace(Config(), match_candidate_patterns=True)
    d = tmp_path / ".tokenomics" / "taxonomy"
    d.mkdir(parents=True)
    (d / "mined.toml").write_text(dump_patterns_toml([_candidate("bust_turns >= 1")]))
    c = _bursty_corpus(n_hit=1)  # 1/12 ≈ 0.08 < 0.25
    c.project_path = str(tmp_path)
    assert not any((f.pattern_id or "") == "mined.bust_turns" for f in taxonomy_match.run(c, cfg))


def test_session_rule_above_hit_ratio_fires(tmp_path):
    cfg = replace(Config(), match_candidate_patterns=True)
    d = tmp_path / ".tokenomics" / "taxonomy"
    d.mkdir(parents=True)
    (d / "mined.toml").write_text(dump_patterns_toml([_candidate("bust_turns >= 1")]))
    c = _bursty_corpus(n_hit=5)  # 5/12 ≈ 0.42 ≥ 0.25
    c.project_path = str(tmp_path)
    fired = [f for f in taxonomy_match.run(c, cfg) if (f.pattern_id or "") == "mined.bust_turns"]
    assert fired and fired[0].evidence["sessions_matched"] == 5


# ── promotion gate ────────────────────────────────────────────────────────────

def test_promote_qualifying_candidate(tmp_path):
    cfg = Config()
    _write_mined(tmp_path, cfg)
    res = promote_candidates(tmp_path, cfg, _mixed_corpus(),
                             pattern_ids=None, today="2026-06-21")
    assert res.ok
    ids = {p.id for p in res.promoted}
    assert "empirical.search_ratio" in ids

    # promoted.toml now holds an empirical record that fires by DEFAULT (no opt-in)
    cat = load_catalog(project_path=tmp_path)
    assert cat.by_id()["empirical.search_ratio"].maturity == "empirical"
    c = _mixed_corpus()
    c.project_path = str(tmp_path)
    fired = taxonomy_match.run(c, cfg)  # default cfg: candidates off
    assert any((f.pattern_id or "") == "empirical.search_ratio" for f in fired)


def test_promote_rejects_low_separation(tmp_path):
    cfg = replace(Config(), thresholds=replace(Config().thresholds, promote_min_separation=2.0))
    _write_mined(tmp_path, cfg)
    res = promote_candidates(tmp_path, cfg, _mixed_corpus(), today="2026-06-21")
    assert not res.ok
    assert res.skipped and all("bar" in why for _, why in res.skipped)
    # mined.toml left intact since nothing was promoted
    assert (tmp_path / ".tokenomics" / "taxonomy" / "mined.toml").exists()


def test_promote_no_mined_file(tmp_path):
    res = promote_candidates(tmp_path, Config(), _mixed_corpus(), today="2026-06-21")
    assert not res.ok
    assert "mine" in res.reason
