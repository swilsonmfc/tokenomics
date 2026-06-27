---
name: tokenomics-advisor-code-indexing
description: Recommends code-context search strategy (grep vs LSP vs AST vs RepoMap vs CocoIndex) to cut search token cost. Reads tokenomics D1 search-efficiency findings and installed plugins, then advises whether to enable an indexer and how. Trigger on 'should I add an indexing tool', 'improve code search', 'grep is slow/expensive', 'reduce search token cost', 'set up LSP/AST/RepoMap', 'why is my context search so expensive'.
---

# Code-indexing advisor

You advise on how this project finds code context, trading expensive full-text scans for
cheaper structured navigation.

## Inputs
1. `.tokenomics/aggregates.json` → `findings` where `analysis_no == 1` (D1: search-heavy
   ratio, repeated patterns, whether an indexer is installed) and `static_env.plugins`.
   If missing/stale, ask the user to run `/tokenomics-scan` first.

## What to do
1. Report the observed search profile: share of tool calls that are text search, repeated
   grep patterns, and absolute search-call volume.
2. State whether a code-indexing tool is installed (e.g. `pyright-lsp`) and whether the
   trajectory actually used it.
3. Recommend by trajectory:
   - **Search-heavy + no indexer** → add one. Compare options for the repo's language:
     LSP (precise symbol nav, best for typed languages), AST/tree-sitter (structural
     queries), RepoMap (whole-repo overview to reduce blind grepping), CocoIndex-Code
     (semantic code index). Give concrete enablement steps.
   - **Indexer installed but unused** → the model is grepping when it could navigate.
     Recommend prompting/agent guidance to prefer symbol lookup over raw grep.
   - **Not search-heavy** → no change; note the repeated patterns to cache/narrow.
4. Quantify expected savings from the D1 estimate (search tokens × reduction factor).

## Guidance
- Match the tool to the language and repo size; don't recommend heavyweight indexing for a
  tiny repo where grep is already cheap.
