"""Static-analysis parsers: frontmatter, CLAUDE.md metrics, MCP, agents/skills."""

from __future__ import annotations

from tokenomics.static_analysis import agents as agents_mod
from tokenomics.static_analysis import skills as skills_mod
from tokenomics.static_analysis._frontmatter import read_frontmatter
from tokenomics.static_analysis.claudemd import _analyze, collect_claude_md
from tokenomics.static_analysis.mcp import collect_mcp

# ── frontmatter ───────────────────────────────────────────────────────────────

def test_read_frontmatter_parses_and_counts_body(tmp_path):
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: my-skill\ndescription: 'Do a thing'\n"
                 "model: claude-haiku-4-5\n---\nline1\nline2\n")
    fm, body = read_frontmatter(f)
    assert fm["name"] == "my-skill"
    assert fm["description"] == "Do a thing"  # surrounding quotes stripped
    assert fm["model"] == "claude-haiku-4-5"
    assert body == 2


def test_read_frontmatter_absent(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("# Title\nbody\n")
    fm, body = read_frontmatter(f)
    assert fm == {}
    assert body == 2


def test_read_frontmatter_missing_file(tmp_path):
    fm, body = read_frontmatter(tmp_path / "nope.md")
    assert fm == {} and body == 0


# ── CLAUDE.md analysis ────────────────────────────────────────────────────────

def test_claudemd_analysis_tokens_lines_dupes(tmp_path):
    text = "# A\n# A\n## B\nsome body text here\n"
    f = tmp_path / "CLAUDE.md"
    f.write_text(text)
    info = _analyze(f, "project")
    assert info["lines"] == 4
    assert info["est_tokens"] == len(text) // 4
    assert info["heading_count"] == 3
    assert "# a" in info["duplicate_headings"]  # case-folded duplicate


def test_collect_claude_md_includes_project(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# H\ncontent\n")
    proj = [d for d in collect_claude_md(tmp_path) if d["scope"] == "project"]
    assert proj and proj[0]["lines"] == 2


# ── MCP ───────────────────────────────────────────────────────────────────────

def test_collect_mcp_project_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"notion": {"type": "stdio"}}}')
    by_name = {s["name"]: s for s in collect_mcp(tmp_path)}
    assert "notion" in by_name
    assert by_name["notion"]["source"] == "project"
    assert by_name["notion"]["type"] == "stdio"


def test_collect_mcp_tolerates_bad_json(tmp_path):
    (tmp_path / ".mcp.json").write_text("{not json")
    # Must not raise; the project simply contributes no servers.
    assert all(s["source"] != "project" for s in collect_mcp(tmp_path))


# ── agents / skills scanners ──────────────────────────────────────────────────

def test_agents_scan_model_pin_and_name_fallback(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "cheap.md").write_text("---\nname: cheap\nmodel: claude-haiku-4-5\n---\nbody\n")
    (d / "inherit.md").write_text("---\ndescription: no pin\n---\nbody\n")
    by = {a["name"]: a for a in agents_mod._scan(d, "plug")}
    assert by["cheap"]["model"] == "claude-haiku-4-5"
    assert by["inherit"]["model"] is None      # inherits — no cheap-model pin
    assert by["inherit"]["name"] == "inherit"  # falls back to file stem


def test_skills_scan_counts_body_lines(tmp_path):
    sk = tmp_path / "skills" / "foo" / "SKILL.md"
    sk.parent.mkdir(parents=True)
    sk.write_text("---\nname: foo\n---\nl1\nl2\nl3\n")
    out = skills_mod._scan(tmp_path / "skills", "plug")
    assert out and out[0]["name"] == "foo" and out[0]["body_lines"] == 3


def test_scanners_empty_on_missing_dir(tmp_path):
    assert agents_mod._scan(tmp_path / "nope", "p") == []
    assert skills_mod._scan(tmp_path / "nope", "p") == []
