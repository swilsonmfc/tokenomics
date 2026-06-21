# Plugin surface

tokenomics ships as a Claude Code plugin. The markdown/JSON surface calls into the Python
core via `uv run --project "${CLAUDE_PLUGIN_ROOT}" python -m tokenomics.cli ...`.

## Manifest

- `.claude-plugin/plugin.json` — name, description, version, author.
- `.claude-plugin/marketplace.json` — lets the plugin install from a directory source.

## Commands (`commands/*.md`)

| Command | CLI | Purpose |
|---|---|---|
| `/tokenomics-scan [--all] [--deep]` | `scan` | Analyze logs + static config → `.tokenomics/report.md` + `aggregates.json`. Default scope is the current project; `--all` aggregates every project under `~/.claude/projects/` (adds a per-project breakdown). |
| `/tokenomics-report` | `report` | Re-render `report.md` from cached `aggregates.json` (no re-scan). |
| `/tokenomics-watch on\|off` | `watch` | Toggle capture mode (`capture_enabled` in `.tokenomics/config.toml`). |

## Capture hook (`hooks/hooks.json` + `capture/`)

Hooks receive event JSON on stdin but NOT token counts, so capture reads the live session
transcript incrementally (byte-offset cache keyed by `sessionId` → only new lines parsed).

| Event | Behavior |
|---|---|
| `SessionStart` | Reset offset, arm capture. |
| `UserPromptSubmit` | Parse new turns, update running totals; warn (stdout → context) on context-growth / cache-bust / budget threshold before the next turn. |
| `PostToolUse` (`*`) | Flag the just-run expensive tool. |
| `Stop` | Append a session-summary flag. |

Rules: idempotent, append-only, always exit 0 fast — a hook must never disrupt the session.
Writes only under `.tokenomics/`. `capture/runner.py` dispatches; `tailer.py` does the
incremental read; `flags.py` evaluates thresholds and appends to `capture.jsonl`.

## Advisory skills (`skills/<name>/SKILL.md`)

Read-only advisors that consume `.tokenomics/aggregates.json` (and live config) — they do
not recompute metrics. If aggregates are missing/stale they tell the user to run a scan.

| Skill | Consumes | Recommends |
|---|---|---|
| `claude-md-linter` | D4 findings + live CLAUDE.md | Streamlined rewrite, per-turn savings, cache-bust warning. |
| `code-indexing-advisor` | D1 findings + plugins | grep vs LSP vs AST vs RepoMap vs CocoIndex; enablement steps. |
| `dynamic-router-advisor` | D2 findings + `by_model` + agent model pins | Task-class → model policy, thinking tiers, cheap-subagent pins. |
| `context-window-evaluator` | D3 findings + context series + static MCP/CLAUDE.md | Offloads, disable unused MCP, compaction cadence. |

## Output layout (`.tokenomics/`, written into the analyzed project)

```
.tokenomics/
├── config.toml            # optional threshold / capture overrides
├── raw/{corpus_meta.json, offset-*.json, running-*.json}
├── aggregates.json        # canonical machine output (findings + metrics)
├── capture.jsonl          # append-only real-time flags
├── report.md              # human report (rendered from aggregates.json)
└── deep/enrichment.json   # only with --deep
```
