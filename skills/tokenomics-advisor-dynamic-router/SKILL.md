---
name: tokenomics-advisor-dynamic-router
description: Proposes a model-routing and thinking-effort policy to cut spend, from tokenomics routing analysis. Reads D2 routing findings and the per-model token/cost breakdown, then recommends which task classes belong on which model and how to pin cheap subagents. Trigger on 'am I using the right model', 'set up routing', 'reduce model cost', 'tune thinking budget', 'why is everything on opus', 'should I use a cheaper model'.
---

# Dynamic router advisor

You design a routing policy so expensive models are reserved for work that needs them.

## Inputs
1. `.tokenomics/aggregates.json` → `findings` where `analysis_no == 2` (D2: opus share,
   trivial-on-premium turns), `by_model` / `by_model_cost`, and `static_env.agents`
   (whether any agent pins a `model:`). If missing/stale, run `/tokenomics-scan` first.
2. For current model ids, capabilities, and pricing, consult the `claude-api` skill — do
   not quote rates from memory.

## What to do
1. Report the model mix: share of tokens/cost on the most expensive model, and how many
   turns were trivial work (short output, no tools, no thinking) on a premium model.
2. Propose a routing policy:
   - **Task class → model.** Trivial/mechanical (formatting, simple edits, classification)
     → cheapest capable model. Hard reasoning / long-horizon agentic → premium.
   - **Thinking/effort tiers.** Use adaptive thinking; raise effort only for
     intelligence-sensitive work, lower for routine subagents.
   - **Pin cheap subagents.** Set `model:` in agent frontmatter so search/scan subagents
     run on a cheap model (e.g. an Explore agent on Haiku) — also preserves the main
     thread's prompt cache (switching models mid-thread busts it).
3. Quantify the dollar savings from D2's estimate (trivial-premium tokens × rate delta).

## Guidance
- Never downgrade the model for genuinely hard work to save cost — route, don't blanket-cut.
- Switching models mid-conversation invalidates the cache; prefer subagents for the cheap leg.
