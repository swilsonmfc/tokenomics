"""Parser + assembler: linkage, schema tolerance, no double-count."""

from __future__ import annotations

from conftest import rec_assistant, rec_user_tool_result, write_jsonl

from tokenomics.assemble import assemble_session
from tokenomics.logpath import SessionFiles


def _session_files(tmp_path, records, subagents=None):
    main = tmp_path / "s1.jsonl"
    write_jsonl(main, records)
    sub_logs = []
    metas = {}
    for agent_id, recs in (subagents or {}).items():
        log = tmp_path / "s1" / "subagents" / f"agent-{agent_id}.jsonl"
        write_jsonl(log, recs)
        sub_logs.append(log)
        meta = tmp_path / "s1" / "subagents" / f"agent-{agent_id}.meta.json"
        meta.write_text('{"agentType": "Explore", "description": "search", '
                        '"toolUseId": "spawn1"}')
        metas[agent_id] = meta
    return SessionFiles("s1", main, sub_logs, metas)


def test_basic_usage_parsed(tmp_path):
    recs = [rec_assistant("u1", usage_dict={
        "input_tokens": 100, "output_tokens": 50,
        "cache_creation_input_tokens": 20, "cache_read_input_tokens": 200})]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    assert len(s.turns) == 1
    u = s.turns[0].usage
    assert (u.input, u.output, u.cache_creation, u.cache_read) == (100, 50, 20, 200)


def test_iterations_not_double_counted(tmp_path):
    # Top-level usage must win; iterations[] is ignored.
    recs = [rec_assistant("u1", usage_dict={
        "input_tokens": 100, "output_tokens": 50,
        "iterations": [{"input_tokens": 100, "output_tokens": 50},
                       {"input_tokens": 100, "output_tokens": 50}]})]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    assert s.turns[0].usage.input == 100  # not 300


def test_string_content_and_unknown_types(tmp_path):
    recs = [
        {"type": "ai-title", "uuid": "x", "title": "hi"},  # unknown -> skipped
        rec_assistant("u1", content="just a string", usage_dict={"input_tokens": 5}),
    ]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    assert len(s.turns) == 1
    assert s.turns[0].text_chars == len("just a string")


def test_compact_summary_skipped_for_usage(tmp_path):
    recs = [rec_assistant("u1", usage_dict={"input_tokens": 99}, isCompactSummary=True)]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    assert s.turns[0].usage is None
    assert s.turns[0].skipped_for_usage is True


def test_malformed_line_skipped(tmp_path):
    main = tmp_path / "s1.jsonl"
    main.write_text('{"type":"assistant","uuid":"u1","message":{"usage":{"input_tokens":7}}}\n'
                    'not json at all\n')
    sf = SessionFiles("s1", main, [], {})
    s = assemble_session(sf, "/tmp/proj")
    assert len(s.turns) == 1


def test_tool_use_and_result_linkage(tmp_path):
    recs = [
        rec_assistant("u1", content=[
            {"type": "tool_use", "id": "tc1", "name": "Read",
             "input": {"file_path": "/a.py"}}], usage_dict={"input_tokens": 1}),
        rec_user_tool_result("u2", "tc1", content="x" * 40, parent="u1"),
    ]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    call = s.turns[0].tool_calls[0]
    assert call.name == "Read"
    assert call.result_chars == 40


def test_mcp_tool_parsed(tmp_path):
    recs = [rec_assistant("u1", content=[
        {"type": "tool_use", "id": "tc1", "name": "mcp__notion__search", "input": {}}],
        usage_dict={"input_tokens": 1})]
    s = assemble_session(_session_files(tmp_path, recs), "/tmp/proj")
    call = s.turns[0].tool_calls[0]
    assert call.is_mcp and call.mcp_server == "notion"


def test_subagent_linkage_and_rollup(tmp_path):
    spawn = rec_assistant("u1", content=[
        {"type": "tool_use", "id": "spawn1", "name": "Agent",
         "input": {"subagent_type": "Explore"}}], usage_dict={"input_tokens": 1})
    result = rec_user_tool_result(
        "u2", "spawn1", parent="u1",
        tool_use_result={"agentId": "abc", "agentType": "Explore", "totalTokens": 60,
                         "usage": {"input_tokens": 10, "output_tokens": 50},
                         "resolvedModel": "claude-haiku-4-5"})
    sub_recs = [rec_assistant("su1", sidechain=True,
                              usage_dict={"input_tokens": 10, "output_tokens": 50})]
    sf = _session_files(tmp_path, [spawn, result], subagents={"abc": sub_recs})
    s = assemble_session(sf, "/tmp/proj")
    assert len(s.subagents) == 1
    sub = s.subagents[0]
    assert sub.rollup_total_tokens == 60
    assert sub.resolved_model == "claude-haiku-4-5"
    assert sub.agent_type == "Explore"
    assert len(sub.turns) == 1
    # main thread excludes sidechain turns
    assert all(not t.is_sidechain for t in s.turns)
