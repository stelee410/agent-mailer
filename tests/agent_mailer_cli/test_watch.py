"""Tests for agent_mailer_cli.watch — the SPEC §15.6 critical invariants.

Reviewer-mandated coverage (P2-1):
  • #2: sessions.json is updated ONLY after a clean claude exit AND a parsed
        session_id. Failed runs (return_code != 0, missing session_id, parse
        error) must NOT write to sessions.json.
  • #3-#4: a non-zero return_code must NOT add the message to processed.txt.
        inflight.json must be cleared whether the run succeeded or failed.
  • Resume routing: an existing fresh session triggers `--resume <id>` +
        RESUME_TEMPLATE prompt.
  • Stale session routing: an existing but expired session triggers no resume
        + a stale-session note appended to the prompt.

Strategy: stub `run_claude` so we don't actually spawn a subprocess; assert
on the args it was called with and the on-disk side-effects.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent_mailer_cli.broker import InboxMessage
from agent_mailer_cli.claude_runner import ClaudeResult
from agent_mailer_cli.config import Config
from agent_mailer_cli.recovery import DeadLetterStore, RetryStore
from agent_mailer_cli.sessions import SessionStore
from agent_mailer_cli.state import LocalState
from agent_mailer_cli import watch as watch_mod


def _stores(cfg_dir: Path):
    return RetryStore(cfg_dir), DeadLetterStore(cfg_dir)


async def _handle(msg, cfg, state, sessions, *, dry_run=False):
    retries, dead = _stores(cfg.cfg_dir)
    await watch_mod._handle_message(
        msg, cfg, state, sessions, retries, dead,
        dry_run=dry_run, max_retries=cfg.max_retries,
    )


def _make_cfg(workdir: Path) -> Config:
    cfg_dir = workdir / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700, exist_ok=True)
    return Config(
        workdir=workdir,
        agent_id="aid-1",
        agent_name="coder",
        address="coder@local",
        broker_url="https://broker.test",
        api_key="key-XYZ",
        permission_mode="acceptEdits",
        poll_interval_idle=60,
        poll_interval_active=10,
        max_retries=3,
        session_max_age_days=7,
        session_max_turns=50,
        claude_command="claude",
    )


def _msg(thread_id: str = "thr-A", msg_id: str = "msg-A") -> InboxMessage:
    return InboxMessage(
        id=msg_id, thread_id=thread_id,
        from_agent="pm@local", to_agent="coder@local",
        subject="ignored — never reaches prompt", is_read=False,
        created_at="2026-05-09T05:00:00Z", raw={},
    )


class _Captured:
    """Holds the cmd/cwd that the patched run_claude was invoked with."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []


def _install_run_claude(monkeypatch: pytest.MonkeyPatch, result: ClaudeResult,
                       captured: _Captured) -> None:
    async def fake_run(cmd, *, cwd, timeout_seconds=1800):  # noqa: ANN001
        captured.calls.append((list(cmd), Path(cwd)))
        return result

    monkeypatch.setattr("agent_mailer_cli.watch.run_claude", fake_run)


# ---------------- invariant #2: sessions.json only on success ----------------


def test_success_records_session_and_processed(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    captured = _Captured()
    _install_run_claude(
        monkeypatch,
        ClaudeResult(
            return_code=0, stdout='{"session_id":"S-1","total_cost_usd":0.01}',
            stderr="", duration_seconds=1.2,
            parsed={"session_id": "S-1", "total_cost_usd": 0.01},
        ),
        captured,
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert "msg-A" in state.processed
    assert state.cursor == "msg-A"
    assert (cfg.cfg_dir / "inflight.json").exists() is False
    rec = sessions.get("thr-A")
    assert rec is not None and rec.session_id == "S-1"


def test_nonzero_return_code_skips_processed_and_sessions(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §15.6 invariants #2 + #4: claude exit != 0 → don't update either map."""
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=1, stdout="", stderr="boom",
                     duration_seconds=0.1, parsed=None),
        _Captured(),
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert "msg-A" not in state.processed
    assert state.cursor is None
    # inflight cleared even on failure (so next poll can retry).
    assert (cfg.cfg_dir / "inflight.json").exists() is False
    assert sessions.get("thr-A") is None


def test_unparseable_json_marks_processed_but_not_session(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """If claude exits cleanly but emits non-JSON output, we still mark the
    message processed (avoid spawn loops) but DO NOT write a sessions.json
    entry — we have nothing to resume from."""
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=0, stdout="not really json", stderr="",
                     duration_seconds=0.1, parsed=None,
                     parse_error="claude stdout was not valid JSON"),
        _Captured(),
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert "msg-A" in state.processed
    assert sessions.get("thr-A") is None


def test_parsed_without_session_id_skips_session_write(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=0, stdout='{"foo":1}', stderr="",
                     duration_seconds=0.1, parsed={"foo": 1}),
        _Captured(),
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert "msg-A" in state.processed
    assert sessions.get("thr-A") is None


# ---------------- resume routing ----------------


def test_existing_fresh_session_triggers_resume(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    sessions.record_success("thr-A", "S-prev")  # establish a fresh prior

    captured = _Captured()
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=0, stdout='{"session_id":"S-prev"}', stderr="",
                     duration_seconds=0.1, parsed={"session_id": "S-prev"}),
        captured,
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert len(captured.calls) == 1
    cmd, _ = captured.calls[0]
    # build_cmd appends `--resume <session_id>` at the tail.
    assert "--resume" in cmd
    assert "S-prev" in cmd
    # The prompt (cmd[2]) is the resume template.
    prompt = cmd[2]
    assert "active thread" in prompt
    assert "fresh thread" not in prompt

    # turn_count should now be 2 (prior turn + this one).
    rec = sessions.get("thr-A")
    assert rec is not None and rec.turn_count == 2


def test_stale_session_does_not_resume_and_appends_note(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    # Hand-roll an ancient sessions.json entry.
    ancient = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    (cfg.cfg_dir / "sessions.json").write_text(json.dumps({
        "thr-A": {"session_id": "S-old", "last_used_at": ancient,
                  "turn_count": 7, "first_seen_at": ancient},
    }))
    sessions = SessionStore(cfg.cfg_dir)

    captured = _Captured()
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=0, stdout='{"session_id":"S-NEW"}', stderr="",
                     duration_seconds=0.1, parsed={"session_id": "S-NEW"}),
        captured,
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    cmd, _ = captured.calls[0]
    assert "--resume" not in cmd
    prompt = cmd[2]
    assert "fresh thread" in prompt
    assert "Prior claude session for this thread expired" in prompt
    assert ".agent-mailer/memory/thr-A.md" in prompt
    # SPEC §11.3 / reviewer P2-1: when the stale session is replaced with a
    # NEW session_id, turn_count must RESET to 1 (not carry over the prior 7).
    # The prior session is gone; the new session has had exactly one turn.
    rec = sessions.get("thr-A")
    assert rec is not None
    assert rec.session_id == "S-NEW"
    assert rec.turn_count == 1


def test_no_prior_session_uses_fresh_template(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    captured = _Captured()
    _install_run_claude(
        monkeypatch,
        ClaudeResult(return_code=0, stdout='{"session_id":"S-FIRST"}', stderr="",
                     duration_seconds=0.1, parsed={"session_id": "S-FIRST"}),
        captured,
    )
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    cmd, _ = captured.calls[0]
    assert "--resume" not in cmd
    prompt = cmd[2]
    assert "fresh thread" in prompt
    assert "Prior claude session" not in prompt


# ---------------- inflight invariant ----------------


def test_inflight_set_during_handle_and_cleared(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """inflight.json must exist between set_inflight and the end of the run."""
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    saw_inflight: list[bool] = []

    async def fake_run(cmd, *, cwd, timeout_seconds=1800):  # noqa: ANN001
        saw_inflight.append((cfg.cfg_dir / "inflight.json").exists())
        return ClaudeResult(return_code=0, stdout='{"session_id":"S"}', stderr="",
                            duration_seconds=0.1, parsed={"session_id": "S"})

    monkeypatch.setattr("agent_mailer_cli.watch.run_claude", fake_run)
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=False))

    assert saw_inflight == [True]  # was inflight when claude was spawned
    assert (cfg.cfg_dir / "inflight.json").exists() is False  # cleared after


def test_dry_run_writes_processed_but_not_session(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    asyncio.run(_handle(_msg(), cfg, state, sessions, dry_run=True))
    assert "msg-A" in state.processed
    assert sessions.get("thr-A") is None  # dry-run never updates sessions
