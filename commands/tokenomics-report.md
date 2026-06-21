---
description: Re-render the tokenomics report.md from the cached aggregates.json (no re-scan)
allowed-tools: [Bash]
---

# /tokenomics-report

Re-render `.tokenomics/report.md` from the already-computed `.tokenomics/aggregates.json`
without re-scanning the logs (cheap). Use after editing thresholds or to refresh the view.

```
uv run --project "${CLAUDE_PLUGIN_ROOT}" python -m tokenomics.cli report --project "$(pwd)"
```

If it reports no `aggregates.json`, run `/tokenomics-scan` first.
