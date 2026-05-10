"""Tests for the AGENT.md ↔ config.toml agent_id consistency check
(SPEC §15.6 invariant #5).
"""
from __future__ import annotations

from pathlib import Path

from agent_mailer_cli.config import Config
from agent_mailer_cli.consistency import check_agent_id_consistency


def _cfg(workdir: Path, agent_id: str) -> Config:
    return Config(
        workdir=workdir,
        agent_id=agent_id,
        agent_name="x", address="x@y", broker_url="https://b", api_key="k",
        permission_mode="acceptEdits",
    )


def test_no_agent_md_means_ok(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, "id-A")
    result = check_agent_id_consistency(tmp_path, cfg)
    assert result.ok is True
    assert result.agent_md_path is None


def test_agent_md_without_id_field_means_ok(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("# Title\n\n- **Name**: foo\n")
    cfg = _cfg(tmp_path, "id-A")
    result = check_agent_id_consistency(tmp_path, cfg)
    assert result.ok is True
    assert result.agent_md_agent_id is None


def test_matching_ids_means_ok(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text(
        "- **Agent ID**: id-A\n"
        "- **Address**: a@b\n"
    )
    cfg = _cfg(tmp_path, "id-A")
    result = check_agent_id_consistency(tmp_path, cfg)
    assert result.ok is True
    assert result.agent_md_agent_id == "id-A"


def test_mismatch_fails_with_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text(
        "- **Agent ID**: id-FROM-AGENT-MD\n"
        "- **Address**: a@b\n"
    )
    cfg = _cfg(tmp_path, "id-FROM-CONFIG")
    result = check_agent_id_consistency(tmp_path, cfg)
    assert result.ok is False
    assert "id-FROM-AGENT-MD" in result.detail
    assert "id-FROM-CONFIG" in result.detail
    assert "--ignore-agent-md-mismatch" in result.detail
