"""Static analysis of the Claude Code 'harness shape'.

Collects installed plugins, skills, agents, hooks, MCP servers, and CLAUDE.md
into a ``StaticEnv``. This install defines most artifacts via PLUGINS, so plugins
are the primary source; user-level dirs are also checked.
"""

from __future__ import annotations

from pathlib import Path

from ..model import StaticEnv
from .agents import collect_agents
from .claudemd import collect_claude_md
from .hooks import collect_hooks
from .mcp import collect_mcp
from .plugins import collect_plugins, plugin_roots
from .skills import collect_skills


def collect_static(project_path: str | Path) -> StaticEnv:
    plugins = collect_plugins()
    roots = plugin_roots(plugins)
    return StaticEnv(
        plugins=plugins,
        skills=collect_skills(roots),
        agents=collect_agents(roots),
        hooks=collect_hooks(roots),
        mcp_servers=collect_mcp(project_path),
        claude_md=collect_claude_md(project_path),
    )


__all__ = ["collect_static"]
