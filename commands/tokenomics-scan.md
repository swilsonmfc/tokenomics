---
description: Diagnose token costs in this project's Claude Code logs and write a savings report to .tokenomics/
argument-hint: "[--deep]"
allowed-tools: [Bash]
---

# /tokenomics-scan

Run the deterministic tokenomics analyzer over this project's Claude Code session
logs and static config, then write `.tokenomics/aggregates.json` + `.tokenomics/report.md`.

Run exactly this (pass `--deep` through only if the user included it in `$ARGUMENTS`):

```
uv run --project "${CLAUDE_PLUGIN_ROOT}" python -m tokenomics.cli scan --project "$(pwd)" $ARGUMENTS
```

Then:
1. Read `.tokenomics/report.md` and summarize the top 3 savings opportunities (by severity
   and estimated savings) for the user.
2. Point them at the relevant advisory skill for each finding (claude-md-linter,
   code-indexing-advisor, dynamic-router-advisor, context-window-evaluator).

Notes:
- The analyzer is deterministic and free; `--deep` adds an optional cheap-model semantic pass.
- If `uv` is unavailable, fall back to `python -m tokenomics.cli` from an environment where
  the `tokenomics` package is installed.
