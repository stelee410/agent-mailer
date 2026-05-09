"""Tests for agent_mailer_cli.memory + the `memory` subcommand group (M4)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent_mailer_cli.memory import (
    GLOBAL_TEMPLATE,
    ensure_global_md,
    ensure_memory_dir,
    global_md_path,
    list_memory_files,
    memory_dir,
    thread_md_path,
)


def _seed_workdir(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700)
    return tmp_path


def test_ensure_memory_dir_creates_with_strict_perms(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    md = ensure_memory_dir(tmp_path)
    assert md.exists() and md.is_dir()
    assert stat.S_IMODE(md.stat().st_mode) == 0o700


def test_ensure_memory_dir_tightens_existing(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    md = memory_dir(tmp_path)
    md.mkdir()
    os.chmod(md, 0o755)
    ensure_memory_dir(tmp_path)
    assert stat.S_IMODE(md.stat().st_mode) == 0o700


def test_ensure_global_md_writes_template(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    p = ensure_global_md(tmp_path, agent_name="coder")
    assert p == global_md_path(tmp_path)
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    body = p.read_text(encoding="utf-8")
    assert "# Global Memory for coder" in body
    assert "Working Style Preferences" in body
    assert "Domain Knowledge" in body
    assert "Avoid Patterns" in body


def test_ensure_global_md_does_not_overwrite_existing(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    ensure_global_md(tmp_path, agent_name="coder")
    p = global_md_path(tmp_path)
    p.write_text("# CUSTOM USER NOTES\n\nDo not clobber.\n", encoding="utf-8")
    again = ensure_global_md(tmp_path, agent_name="coder")
    assert again == p
    # Existing content untouched.
    assert p.read_text(encoding="utf-8") == "# CUSTOM USER NOTES\n\nDo not clobber.\n"


def test_ensure_global_md_handles_missing_agent_name(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    p = ensure_global_md(tmp_path, agent_name="")
    assert "# Global Memory for this agent" in p.read_text(encoding="utf-8")


def test_list_memory_files_empty(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    assert list_memory_files(tmp_path) == []


def test_list_memory_files_returns_md_only(tmp_path: Path) -> None:
    _seed_workdir(tmp_path)
    md = ensure_memory_dir(tmp_path)
    (md / "global.md").write_text("# global\n")
    (md / "thr-1.md").write_text("# thread\n")
    (md / "ignore.txt").write_text("not markdown\n")
    out = list_memory_files(tmp_path)
    names = [p.name for p in out]
    assert "global.md" in names
    assert "thr-1.md" in names
    assert "ignore.txt" not in names


def test_thread_md_path_uses_id(tmp_path: Path) -> None:
    p = thread_md_path(tmp_path, "abc-123")
    assert p.name == "abc-123.md"
    assert p.parent == memory_dir(tmp_path)


def test_global_template_constants_well_formed() -> None:
    # The template must accept the agent_name kwarg without other format vars.
    out = GLOBAL_TEMPLATE.format(agent_name="x")
    assert "Global Memory for x" in out
    # No leftover unfilled placeholders.
    assert "{" not in out and "}" not in out
