"""Unit tests for agent_mailer_cli.security."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_mailer_cli.config import Config, save_config
from agent_mailer_cli.security import (
    SecurityError,
    check_workdir_security,
    ensure_gitignore,
    fix_permissions,
    gitignore_covers,
    watcher_lock,
)


def _seed_config(tmp_path: Path) -> None:
    cfg = Config(
        workdir=tmp_path,
        agent_id="x", agent_name="x", address="x", broker_url="x", api_key="x",
        permission_mode="acceptEdits",
    )
    save_config(cfg)


def test_check_passes_with_strict_perms(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    check_workdir_security(tmp_path)  # no raise


def test_check_rejects_world_readable_config(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    cfg_path = tmp_path / ".agent-mailer" / "config.toml"
    os.chmod(cfg_path, 0o644)
    with pytest.raises(SecurityError) as exc:
        check_workdir_security(tmp_path)
    assert "config.toml" in str(exc.value)
    assert "chmod 600" in str(exc.value)


def test_check_rejects_world_executable_dir(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    cfg_dir = tmp_path / ".agent-mailer"
    os.chmod(cfg_dir, 0o755)
    with pytest.raises(SecurityError) as exc:
        check_workdir_security(tmp_path)
    assert ".agent-mailer" in str(exc.value)
    assert "chmod 700" in str(exc.value)


def test_check_complains_if_missing(tmp_path: Path) -> None:
    with pytest.raises(SecurityError):
        check_workdir_security(tmp_path)


def test_fix_permissions_idempotent(tmp_path: Path) -> None:
    _seed_config(tmp_path)
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_path = cfg_dir / "config.toml"
    os.chmod(cfg_dir, 0o755)
    os.chmod(cfg_path, 0o644)
    fix_permissions(tmp_path)
    assert (cfg_dir.stat().st_mode & 0o777) == 0o700
    assert (cfg_path.stat().st_mode & 0o777) == 0o600


def test_ensure_gitignore_creates_when_missing(tmp_path: Path) -> None:
    modified, path = ensure_gitignore(tmp_path)
    assert modified is True
    assert path.read_text() == ".agent-mailer/\n"


def test_ensure_gitignore_appends(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.pyc\n.venv/\n")
    modified, path = ensure_gitignore(tmp_path)
    assert modified is True
    text = path.read_text()
    assert text.endswith(".agent-mailer/\n")
    assert "*.pyc" in text


def test_ensure_gitignore_idempotent(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".agent-mailer/\nfoo\n")
    modified, _ = ensure_gitignore(tmp_path)
    assert modified is False


def test_gitignore_covers_accepts_no_slash_form(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".agent-mailer\n")
    assert gitignore_covers(tmp_path) is True


def test_gitignore_covers_returns_false_when_missing(tmp_path: Path) -> None:
    assert gitignore_covers(tmp_path) is False


def test_watcher_lock_blocks_second_holder(tmp_path: Path) -> None:
    with watcher_lock(tmp_path):
        with pytest.raises(SecurityError) as exc:
            with watcher_lock(tmp_path):
                pass
        assert "already running" in str(exc.value)
