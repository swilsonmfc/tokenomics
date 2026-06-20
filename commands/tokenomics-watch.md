---
description: Toggle tokenomics capture mode (real-time waste flagging) on or off
argument-hint: "on | off"
allowed-tools: [Bash]
---

# /tokenomics-watch

Toggle capture mode, which flags context-window growth, cache-busting, and budget overruns
in real time during a session (written to `.tokenomics/capture.jsonl`, surfaced before the
next turn). The capture hook itself is registered by the plugin; this just sets the
`capture_enabled` flag in `.tokenomics/config.toml`.

```
uv run --project "${CLAUDE_PLUGIN_ROOT}" python -m tokenomics.cli watch $ARGUMENTS --project "$(pwd)"
```

`$ARGUMENTS` must be `on` or `off`.
