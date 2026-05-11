"""Unit tests for agent_mailer_cli.agent_md."""
from __future__ import annotations

from pathlib import Path

from agent_mailer_cli.agent_md import find_agent_md, parse_agent_md


def test_parse_bullet_list(tmp_path: Path) -> None:
    md = tmp_path / "AGENT.md"
    md.write_text(
        "# Agent Identity\n\n"
        "- **Name**: coder\n"
        "- **Role**: software engineer\n"
        "- **Address**: coder@admin.example.com\n"
        "- **Agent ID**: 75f2b194-4b91-4c19-8e97-4ff5fe562ece\n"
        "- **Broker URL**: https://broker.example.com\n"
    )
    info = parse_agent_md(md)
    assert info.agent_name == "coder"
    assert info.agent_role == "software engineer"
    assert info.address == "coder@admin.example.com"
    assert info.agent_id == "75f2b194-4b91-4c19-8e97-4ff5fe562ece"
    assert info.broker_url == "https://broker.example.com"


def test_parse_skips_protocol_section(tmp_path: Path) -> None:
    """A protocol section that documents a sample agent_id must NOT clobber identity."""
    md = tmp_path / "AGENT.md"
    md.write_text(
        "- **Agent ID**: real-id-001\n"
        "- **Address**: real@example.com\n"
        "\n"
        "## 邮箱协议\n"
        "Sample request:\n"
        "GET /agents/sample-id-FAKE\n"
        "- **Agent ID**: SAMPLE-FAKE\n"
    )
    info = parse_agent_md(md)
    assert info.agent_id == "real-id-001"


def test_parse_ignores_code_blocks(tmp_path: Path) -> None:
    md = tmp_path / "AGENT.md"
    md.write_text(
        "- **Name**: coder\n"
        "\n"
        "```\n"
        "- **Name**: not-coder\n"
        "```\n"
    )
    info = parse_agent_md(md)
    assert info.agent_name == "coder"


def test_parse_returns_empty_for_missing_file(tmp_path: Path) -> None:
    info = parse_agent_md(tmp_path / "nope.md")
    assert info.is_empty()


def test_find_agent_md(tmp_path: Path) -> None:
    assert find_agent_md(tmp_path) is None
    (tmp_path / "AGENT.md").write_text("# x\n")
    assert find_agent_md(tmp_path) == tmp_path / "AGENT.md"


def test_parse_strips_backticks_around_value(tmp_path: Path) -> None:
    md = tmp_path / "AGENT.md"
    md.write_text("- **Address**: `coder@local`\n")
    info = parse_agent_md(md)
    assert info.address == "coder@local"
