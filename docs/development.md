# Development

## Setup & workflow

```bash
uv sync --extra dev                    # Python 3.12 env + pytest + ruff
uv run pytest                          # unit tests (synthetic fixtures, no network)
uv run ruff check src/ tests/          # lint
uv run ruff check --fix src/ tests/    # autofix
uv build                               # wheel + sdist
```

Run the analyzer against any project that has Claude Code logs:

```bash
uv run python -m tokenomics.cli scan --project /path/to/project
uv run python -m tokenomics.cli reconcile --project /path/to/project  # token-accounting gate
```

## Testing strategy

Tests use hand-built synthetic data, never the real corpus, so they're fast and
deterministic.

- `tests/conftest.py` — builders: `usage()`, `tool()`, `turn()`, `session()`,
  `subagent()`, `corpus()` construct model objects directly; `rec_assistant()`,
  `rec_user_tool_result()`, `write_jsonl()` build raw JSONL for parser tests.
- `test_assemble.py` — parser/linkage, schema tolerance, the no-double-count invariant.
- `test_metrics.py` — golden cost numbers, normalization, reconciliation.
- `test_detectors.py` — each detector: one trigger fixture + one negative control, with
  thresholds pinned via the `cfg` fixture for boundary testing.
- `test_capture.py` — offset advances, flags fire once, runner exits 0 on garbage.
- `test_report_and_deep.py` — report sections render; `--deep` runs with a stubbed client.

Detector tests import via `from conftest import ...` (pytest puts `tests/` on the path).

## Conventions

- Detectors are pure (no file I/O); all thresholds live in `config.Thresholds`.
- Keep the deterministic core free of network/LLM calls — only `enrich/deep.py` may call a
  model, and it must be strictly additive (never changes a metric) and injectable for tests.
- When touching pricing or model ids, pull current values from the `claude-api` skill and
  update `config.MODEL_PRICES` — do not hardcode from memory.
- Ruff config (line length 100, rules E/F/I/UP/B) is in `pyproject.toml`.

## A useful self-check

This repo accumulates its own Claude Code logs, so you can dogfood the tool on itself:
`uv run python -m tokenomics.cli scan --project "$(pwd)"` then read `.tokenomics/report.md`.
The subagent reconciliation line in the report is the live correctness gate.
