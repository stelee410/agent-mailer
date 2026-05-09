"""Tests for the `logs` subcommand and log.jsonl 0600 hardening (M6)."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from agent_mailer_cli.commands import logs_cmd
from agent_mailer_cli.config import Config, save_config
from agent_mailer_cli.state import LocalState


def _seed_workdir(tmp_path: Path) -> Path:
    cfg = Config(
        workdir=tmp_path,
        agent_id="x", agent_name="x", address="x@y", broker_url="https://b",
        api_key="k", permission_mode="acceptEdits",
    )
    save_config(cfg)
    return tmp_path


def test_log_jsonl_created_at_0600(tmp_path: Path) -> None:
    """M6: log.jsonl must be 0600 from byte one (was 0644 in M2)."""
    _seed_workdir(tmp_path)
    state = LocalState(tmp_path / ".agent-mailer")
    state.append_log("watch_started", agent="x")
    assert state.log_path.exists()
    assert stat.S_IMODE(state.log_path.stat().st_mode) == 0o600


def test_log_jsonl_tightens_pre_existing_644(tmp_path: Path) -> None:
    """If somehow an old 0644 log.jsonl exists, the next append tightens it."""
    _seed_workdir(tmp_path)
    state = LocalState(tmp_path / ".agent-mailer")
    state.log_path.write_text('{"event":"old"}\n', encoding="utf-8")
    os.chmod(state.log_path, 0o644)

    state.append_log("watch_started", agent="x")
    assert stat.S_IMODE(state.log_path.stat().st_mode) == 0o600


def test_logs_tail_default(tmp_path: Path,
                            capsys: pytest.CaptureFixture[str]) -> None:
    _seed_workdir(tmp_path)
    state = LocalState(tmp_path / ".agent-mailer")
    for i in range(50):
        state.append_log("poll_inbox", n=i)
    rc = logs_cmd.run(tmp_path, tail_n=5, pattern=None)
    out = capsys.readouterr().out
    assert rc == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 5
    # Last line should be the very latest event.
    last = json.loads(lines[-1])
    assert last["event"] == "poll_inbox"
    assert last["n"] == 49


def test_logs_grep_filters(tmp_path: Path,
                            capsys: pytest.CaptureFixture[str]) -> None:
    _seed_workdir(tmp_path)
    state = LocalState(tmp_path / ".agent-mailer")
    state.append_log("poll_inbox", n=1)
    state.append_log("dead_letter", msg_id="m-1")
    state.append_log("poll_inbox", n=2)
    state.append_log("dead_letter", msg_id="m-2")

    rc = logs_cmd.run(tmp_path, tail_n=10, pattern="dead_letter")
    out = capsys.readouterr().out
    assert rc == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 2
    assert all("dead_letter" in line for line in lines)


def test_logs_no_file_returns_zero(tmp_path: Path,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    _seed_workdir(tmp_path)
    rc = logs_cmd.run(tmp_path, tail_n=10, pattern=None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no log.jsonl" in out


def test_logs_without_config_errors(tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    rc = logs_cmd.run(tmp_path, tail_n=10, pattern=None)
    out = capsys.readouterr().err
    assert rc == 2
    assert "No config.toml" in out
