---
name: tokenomics-advisor-context-window
description: Evaluates context-window size and what's loaded into it, recommending offloads to cut standing per-turn token cost. Reads tokenomics D3 context findings, the per-session peak/avg series, and static MCP/CLAUDE.md/agent config. Trigger on 'is my context too big', 'evaluate context window', "what's loaded into context", 'reduce context size', 'why is each turn so expensive', 'should I disable MCP servers'.
---

# Context window evaluator

You evaluate how large the working context is and what's filling it, so standing per-turn
cost (paid on every request) can be reduced.

## Inputs
1. `.tokenomics/aggregates.json` → `findings` where `analysis_no == 3` (D3: peak/avg
   context, contributors, unused-but-loaded MCP servers), `context_series_summary`,
   `mcp_servers_used`, and `static_env` (`mcp_servers`, `claude_md`, `agent_count`).
   If missing/stale, run `/tokenomics-scan` first.

## What to do
1. Report peak and average context per session (with the per-session sparkline if useful),
   and flag sessions over the thresholds.
2. Attribute the standing context to its contributors:
   - **MCP tool schemas** — count distinct servers loaded; call out any loaded-but-never-
     called (pure overhead) and recommend disabling them.
   - **CLAUDE.md** — its token size (re-sent every turn); hand off to the tokenomics-advisor-claude
     skill if large.
   - **Large agent prompts / monotonic growth without compaction.**
3. Recommend offloads: move heavy work to subagents (fresh context), disable unused MCP
   servers, trim CLAUDE.md, and compact long sessions on a cadence.
4. Quantify each contributor's standing per-turn cost (tokens × the per-turn rate, since it
   recurs every request).

## Guidance
- Distinguish a one-off large turn from sustained high average — sustained cost is the one
  worth fixing.
- Disabling an MCP server only helps if its tools really aren't used; check `mcp_servers_used`.
