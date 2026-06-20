"""D3 — Context window management: peak/avg size, contributors, unused MCP."""

from __future__ import annotations

from ..config import Config
from ..metrics import session_context_peak_avg
from ..model import Corpus
from .base import Finding, Severity


class ContextWindowDetector:
    id = "context_window"
    title = "Context window management"
    analysis_no = 3

    def run(self, corpus: Corpus, cfg: Config) -> list[Finding]:
        th = cfg.thresholds
        findings: list[Finding] = []

        peaks: list[tuple[str, int, float]] = []
        for session in corpus.sessions:
            peak, avg = session_context_peak_avg(session)
            if peak:
                peaks.append((session.session_id, peak, avg))
        if not peaks:
            return []

        worst = max(peaks, key=lambda x: x[1])
        global_avg = sum(a for _, _, a in peaks) / len(peaks)
        high_peaks = [p for p in peaks if p[1] > th.ctx_peak]

        # MCP context attribution: distinct servers loaded (each ships tool schemas).
        mcp_servers = set()
        used_servers: set[str] = set()
        for session in corpus.sessions:
            for turn in session.turns:
                for call in turn.tool_calls:
                    if call.is_mcp and call.mcp_server:
                        mcp_servers.add(call.mcp_server)
                        used_servers.add(call.mcp_server)

        if high_peaks or global_avg > th.ctx_avg:
            sev = Severity.HIGH if high_peaks else Severity.MED
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=sev,
                title=(f"Large context windows: peak {worst[1]:,} tok "
                       f"(avg {global_avg:,.0f})"),
                evidence={
                    "peak_session": worst[0],
                    "peak_tokens": worst[1],
                    "avg_context": round(global_avg),
                    "sessions_over_peak_threshold": len(high_peaks),
                    "mcp_servers_in_context": sorted(mcp_servers),
                },
                est_savings_weight=max(0, global_avg - th.ctx_avg) / 1_000_000 * 5,
                recommendation=(
                    "Offload heavy work to subagents (fresh context), trim CLAUDE.md, "
                    "disable MCP servers you don't call, and compact long sessions. "
                    "See the context-window-evaluator skill."
                ),
                deep_enrichable=True,
            ))

        # Loaded-but-unused MCP servers from static config (pure context overhead).
        static_servers = {s.get("name") for s in corpus.static.mcp_servers if s.get("name")}
        unused = sorted(s for s in static_servers if s and s not in used_servers)
        if unused:
            findings.append(Finding(
                detector_id=self.id, analysis_no=self.analysis_no, severity=Severity.LOW,
                title=f"{len(unused)} MCP server(s) loaded but never called",
                evidence={"unused_mcp_servers": unused},
                recommendation="Disable unused MCP servers — their tool schemas sit "
                               "in every request's context for no benefit.",
            ))
        return findings


DETECTOR = ContextWindowDetector()
