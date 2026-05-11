"""Tests for SPEC §13 fault-tolerance: retries.json, dead_letter.jsonl,
recover_inflight.

Reviewer-mandated coverage (M5):
  • retry_count persists across watcher restarts
  • after max_retries failures, msg moves to dead_letter.jsonl and is
    excluded from the next poll
  • inflight age < 15min → wait; >= 15min → bump retry; bump past budget
    → dead-letter
  • dead_letter.jsonl is 0600 immediately on creation (M6 hardening)
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_mailer_cli.broker import InboxMessage
from agent_mailer_cli.claude_runner import ClaudeResult
from agent_mailer_cli.config import Config
from agent_mailer_cli.recovery import (
    DEFAULT_INFLIGHT_AGE_SECONDS,
    DeadLetterRecord,
    DeadLetterStore,
    RetryStore,
    recover_inflight,
)
from agent_mailer_cli.sessions import SessionStore
from agent_mailer_cli.state import LocalState
from agent_mailer_cli import watch as watch_mod


# -------- RetryStore --------


def test_retry_store_round_trip(tmp_path: Path) -> None:
    s = RetryStore(tmp_path)
    assert s.get("m-1") == 0
    assert s.increment("m-1") == 1
    assert s.increment("m-1") == 2
    s2 = RetryStore(tmp_path)
    assert s2.get("m-1") == 2
    s2.clear("m-1")
    assert s2.get("m-1") == 0
    s3 = RetryStore(tmp_path)
    assert s3.get("m-1") == 0


def test_retry_store_handles_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "retries.json").write_text("{not json")
    s = RetryStore(tmp_path)
    assert s.get("anything") == 0
    assert s.increment("anything") == 1


# -------- DeadLetterStore --------


def test_dead_letter_append_creates_at_0600(tmp_path: Path) -> None:
    """M6 hardening: dead_letter.jsonl must be created at 0600 from byte one."""
    s = DeadLetterStore(tmp_path)
    s.append(DeadLetterRecord(msg_id="m-1", thread_id="t-1", retries=3,
                              last_error="boom", stuck_at="2026-05-09T07:00:00+00:00"))
    assert s.path.exists()
    assert stat.S_IMODE(s.path.stat().st_mode) == 0o600


def test_dead_letter_round_trip(tmp_path: Path) -> None:
    s = DeadLetterStore(tmp_path)
    s.append(DeadLetterRecord(msg_id="m-1", thread_id="t-1", retries=3,
                              last_error="boom", stuck_at="2026-05-09T07:00:00+00:00"))
    s.append(DeadLetterRecord(msg_id="m-2", thread_id="t-2", retries=3,
                              last_error="kaboom", stuck_at="2026-05-09T07:00:00+00:00"))
    rs = s.all_records()
    assert [r.msg_id for r in rs] == ["m-1", "m-2"]


def test_dead_letter_remove_keeps_other_records(tmp_path: Path) -> None:
    s = DeadLetterStore(tmp_path)
    s.append(DeadLetterRecord(msg_id="m-1", thread_id="t-1", retries=3,
                              last_error="a", stuck_at="t1"))
    s.append(DeadLetterRecord(msg_id="m-2", thread_id="t-2", retries=3,
                              last_error="b", stuck_at="t2"))
    removed = s.remove("m-1")
    assert removed is not None and removed.msg_id == "m-1"
    survivors = [r.msg_id for r in s.all_records()]
    assert survivors == ["m-2"]


def test_dead_letter_remove_missing_returns_none(tmp_path: Path) -> None:
    s = DeadLetterStore(tmp_path)
    s.append(DeadLetterRecord(msg_id="m-1", thread_id="t-1", retries=3,
                              last_error="a", stuck_at="t"))
    assert s.remove("never-existed") is None


def test_dead_letter_purge(tmp_path: Path) -> None:
    s = DeadLetterStore(tmp_path)
    for i in range(5):
        s.append(DeadLetterRecord(msg_id=f"m-{i}", thread_id="t", retries=3,
                                  last_error="x", stuck_at="t"))
    assert s.purge() == 5
    assert s.purge() == 0


# -------- recover_inflight --------


def test_recover_inflight_no_file_is_noop(tmp_path: Path) -> None:
    retries = RetryStore(tmp_path)
    dead = DeadLetterStore(tmp_path)
    action = recover_inflight(tmp_path / "inflight.json",
                              retries=retries, dead_letter=dead, max_retries=3)
    assert action.action == "noop"


def test_recover_inflight_young_record_waits(tmp_path: Path) -> None:
    retries = RetryStore(tmp_path)
    dead = DeadLetterStore(tmp_path)
    inflight = tmp_path / "inflight.json"
    fresh_iso = datetime.now(timezone.utc).isoformat()
    inflight.write_text(json.dumps({
        "msg_id": "m-1", "thread_id": "t-1",
        "started_at": fresh_iso, "retry_count": 0,
    }))
    action = recover_inflight(inflight, retries=retries, dead_letter=dead, max_retries=3)
    assert action.action == "wait"
    # File preserved so the next watcher poll can finish the run.
    assert inflight.exists()
    # Retries map unaffected.
    assert retries.get("m-1") == 0


def test_recover_inflight_old_record_retries(tmp_path: Path) -> None:
    retries = RetryStore(tmp_path)
    dead = DeadLetterStore(tmp_path)
    inflight = tmp_path / "inflight.json"
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    inflight.write_text(json.dumps({
        "msg_id": "m-1", "thread_id": "t-1",
        "started_at": old_iso, "retry_count": 0,
    }))
    action = recover_inflight(inflight, retries=retries, dead_letter=dead, max_retries=3)
    assert action.action == "retry"
    assert retries.get("m-1") == 1
    # Inflight cleared so next poll can pick up cleanly.
    assert not inflight.exists()
    # Not in dead-letter yet.
    assert dead.all_records() == []


def test_recover_inflight_exhausted_goes_to_dead_letter(tmp_path: Path) -> None:
    retries = RetryStore(tmp_path)
    dead = DeadLetterStore(tmp_path)
    # Pre-load the retry counter near the budget.
    retries.increment("m-1")
    retries.increment("m-1")  # count = 2, max_retries = 3, next bump → 3 == budget
    inflight = tmp_path / "inflight.json"
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    inflight.write_text(json.dumps({
        "msg_id": "m-1", "thread_id": "t-1", "started_at": old_iso,
    }))
    action = recover_inflight(inflight, retries=retries, dead_letter=dead, max_retries=3)
    assert action.action == "dead_letter"
    assert action.retry_count == 3
    assert not inflight.exists()
    assert retries.get("m-1") == 0  # cleared after dead-letter
    rs = dead.all_records()
    assert len(rs) == 1
    assert rs[0].msg_id == "m-1"


def test_recover_inflight_corrupt_inflight_clears_silently(tmp_path: Path) -> None:
    retries = RetryStore(tmp_path)
    dead = DeadLetterStore(tmp_path)
    inflight = tmp_path / "inflight.json"
    inflight.write_text("{not json")
    action = recover_inflight(inflight, retries=retries, dead_letter=dead, max_retries=3)
    assert action.action == "noop"
    assert not inflight.exists()


# -------- _record_failure: end-to-end via watch._handle_message --------


def _make_cfg(workdir: Path, max_retries: int = 3) -> Config:
    cfg_dir = workdir / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700, exist_ok=True)
    return Config(
        workdir=workdir,
        agent_id="aid", agent_name="x", address="x@y", broker_url="https://b",
        api_key="k", permission_mode="acceptEdits",
        max_retries=max_retries,
    )


def _msg() -> InboxMessage:
    return InboxMessage(id="m-fail", thread_id="t-1",
                        from_agent="x@y", to_agent="z@y",
                        subject="x", is_read=False,
                        created_at="2026-05-09T07:00:00Z", raw={})


def test_repeated_failures_lead_to_dead_letter(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path, max_retries=3)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    retries = RetryStore(cfg.cfg_dir)
    dead = DeadLetterStore(cfg.cfg_dir)

    async def always_fails(cmd, *, cwd, timeout_seconds=1800):  # noqa: ANN001
        return ClaudeResult(return_code=1, stdout="", stderr="boom",
                            duration_seconds=0.1, parsed=None)

    monkeypatch.setattr("agent_mailer_cli.watch.run_claude", always_fails)

    # Three back-to-back failures: 1st and 2nd just bump count, 3rd → dead-letter.
    for i in range(3):
        asyncio.run(watch_mod._handle_message(
            _msg(), cfg, state, sessions, retries, dead,
            dry_run=False, max_retries=cfg.max_retries,
        ))

    # Message is now in dead_letter and processed (so future polls skip it).
    assert "m-fail" in state.processed
    assert retries.get("m-fail") == 0  # cleared after dead-letter
    rs = dead.all_records()
    assert len(rs) == 1
    assert rs[0].msg_id == "m-fail"
    assert rs[0].retries == 3


def test_failure_then_success_clears_retry_count(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _make_cfg(tmp_path, max_retries=5)
    state = LocalState(cfg.cfg_dir)
    sessions = SessionStore(cfg.cfg_dir)
    retries = RetryStore(cfg.cfg_dir)
    dead = DeadLetterStore(cfg.cfg_dir)

    call_n = {"i": 0}

    async def flaky(cmd, *, cwd, timeout_seconds=1800):  # noqa: ANN001
        call_n["i"] += 1
        if call_n["i"] == 1:
            return ClaudeResult(return_code=1, stdout="", stderr="bad",
                                duration_seconds=0.1, parsed=None)
        return ClaudeResult(return_code=0, stdout='{"session_id":"S"}', stderr="",
                            duration_seconds=0.1, parsed={"session_id": "S"})

    monkeypatch.setattr("agent_mailer_cli.watch.run_claude", flaky)

    asyncio.run(watch_mod._handle_message(_msg(), cfg, state, sessions, retries, dead,
                                          dry_run=False, max_retries=cfg.max_retries))
    assert retries.get("m-fail") == 1
    assert "m-fail" not in state.processed

    asyncio.run(watch_mod._handle_message(_msg(), cfg, state, sessions, retries, dead,
                                          dry_run=False, max_retries=cfg.max_retries))
    assert retries.get("m-fail") == 0  # cleared on success
    assert "m-fail" in state.processed
    assert dead.all_records() == []
