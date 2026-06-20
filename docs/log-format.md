# Claude Code session log format

The signal source. Logs live at `~/.claude/projects/<namespaced>/` where `<namespaced>`
is the project's absolute path with `/` and `.` replaced by `-`
(`/Users/x/Projects/foo` → `-Users-x-Projects-foo`). Git worktrees get their own folder.

## Files

- `<sessionId>.jsonl` — one top-level session (JSONL, one record per line).
- `<sessionId>/subagents/agent-<agentId>.jsonl` — a subagent transcript.
- `<sessionId>/subagents/agent-<agentId>.meta.json` — `{agentType, description, toolUseId}`.

`logpath.discover_sessions()` returns these grouped as `SessionFiles`.

## Record types

Each line has a `type`. We process `assistant`, `user`, `system`; everything else
(`file-history-snapshot, mode, permission-mode, last-prompt, ai-title, agent-name,
bridge-session, queue-operation`) is skipped. Common envelope keys: `uuid`, `parentUuid`,
`timestamp` (ISO-8601), `sessionId`, `isSidechain`, `gitBranch`, `version`, `entrypoint`,
and on assistant turns `requestId`, `attributionPlugin`, `attributionSkill`.

## Where each signal lives

| Signal | Path |
|---|---|
| Token usage | `message.usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`, plus `cache_creation.{ephemeral_1h_input_tokens, ephemeral_5m_input_tokens}` and `server_tool_use.{web_search_requests, web_fetch_requests}` |
| ⚠️ Do NOT use | `message.usage.iterations[]` — repeats per-iteration counts (double-counts) |
| Model | `message.model` (e.g. `claude-opus-4-8`) |
| Content blocks | `message.content[]` of type `text` / `thinking` / `tool_use` (content may also be a bare string) |
| Tool call | `tool_use` block: `{id, name, input, caller.type}`. MCP tools named `mcp__<server>__<tool>` |
| Tool result | a `user` record with a `tool_result` block (`tool_use_id` links back to `tool_use.id`) |
| Skip-for-usage | top-level `isCompactSummary` / `isApiErrorMessage` |
| Plugin/skill attribution | top-level `attributionPlugin` / `attributionSkill` on assistant turns |

## Subagent linkage

1. **Spawn**: an assistant `tool_use` block with `name` in `{Agent, Task}` and an `id`.
2. **Rollup**: the matching `user` record carries a top-level `toolUseResult` with
   `{agentId, agentType, resolvedModel, totalTokens, totalToolUseCount, totalDurationMs,
   usage, toolStats}`.
3. **Transcript**: the file `agent-<agentId>.jsonl` (every record `isSidechain: true`,
   first record `parentUuid: null`), shares the parent `sessionId`.

Linkage chain: parent `tool_use.id` == meta `toolUseId` == result `tool_use_id`;
`toolUseResult.agentId` == the `agent-<agentId>.jsonl` filename. `assemble.py` joins these.

**`toolUseResult.totalTokens` is the subagent's final-turn usage total, not a sum.** Sum the
transcript turns for billing; use the rollup only to cross-check linkage.

## Scale

~tens of MB across many files; largest single file a few MB. Stream line-by-line; parsing
is parallelizable per file but fast enough single-threaded for one project.
