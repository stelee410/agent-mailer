"""Tests for agent_mailer_cli.state — atomic writes, processed.txt, inflight,
and SessionStore (M3).

Reviewer-mandated coverage (P2-1):
  • atomic write: a SIGKILL mid-write must leave the previous version intact
    (we can't truly SIGKILL pytest, but we can simulate by interrupting between
    the temp file and the os.replace step).
  • processed.txt is append-only; no row is lost across reopens.
  • SessionStore: record_success / freshness / prune.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_mailer_cli.sessions import SessionRecord, SessionStore, is_session_fresh
from agent_mailer_cli.state import LocalState, _atomic_write_text


def test_atomic_write_replaces_previous_content(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("OLD\n")
    _atomic_write_text(target, "NEW\n")
    assert target.read_text() == "NEW\n"


def test_atomic_write_no_temp_file_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    _atomic_write_text(target, "X\n")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp.")]
    assert leftovers == []


def test_atomic_write_torn_write_simulation(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a process death between writing the temp file and os.replace.

    The original file content must be intact and no half-written content
    must be visible at `target`.
    """
    target = tmp_path / "important.txt"
    target.write_text("INTACT-OLD\n")

    # Make os.replace blow up to mimic the process dying mid-rename.
    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("simulated SIGKILL between fsync and rename")

    monkeypatch.setattr("agent_mailer_cli.state.os.replace", boom)
    with pytest.raises(RuntimeError):
        _atomic_write_text(target, "WOULD-BE-NEW\n")

    # The previous version is still readable verbatim.
    assert target.read_text() == "INTACT-OLD\n"
    # The temp file is also cleaned up — we don't leak garbage in cfg dir.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp.")]
    assert leftovers == [], f"temp file leaked: {leftovers}"


def test_processed_txt_append_only_survives_reopen(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir()

    s1 = LocalState(cfg_dir)
    s1.add_processed("msg-1")
    s1.add_processed("msg-2")
    s1.add_processed("msg-3")

    s2 = LocalState(cfg_dir)
    assert s2.processed == {"msg-1", "msg-2", "msg-3"}
    s2.add_processed("msg-4")

    s3 = LocalState(cfg_dir)
    assert s3.processed == {"msg-1", "msg-2", "msg-3", "msg-4"}
    # Each line written exactly once, no duplicates.
    raw = (cfg_dir / "processed.txt").read_text()
    assert raw.count("msg-1\n") == 1
    assert raw.count("msg-4\n") == 1


def test_processed_txt_idempotent_add(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir()
    s = LocalState(cfg_dir)
    s.add_processed("m")
    s.add_processed("m")
    s.add_processed("m")
    assert (cfg_dir / "processed.txt").read_text() == "m\n"


def test_inflight_set_and_clear(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir()
    s = LocalState(cfg_dir)
    s.set_inflight("msg-x", "thr-y")
    rec = s.load_inflight()
    assert rec is not None
    assert rec.msg_id == "msg-x"
    assert rec.thread_id == "thr-y"
    s.clear_inflight()
    assert s.load_inflight() is None


def test_inflight_load_returns_none_when_corrupt(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir()
    (cfg_dir / "inflight.json").write_text("{not json")
    s = LocalState(cfg_dir)
    assert s.load_inflight() is None


# --------------------- SessionStore tests ---------------------


def test_session_store_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    assert store.get("thr-1") is None
    rec = store.record_success("thr-1", "sess-A")
    assert rec.session_id == "sess-A"
    assert rec.turn_count == 1
    assert rec.first_seen_at == rec.last_used_at

    # Reopen and confirm persistence.
    store2 = SessionStore(tmp_path)
    rec2 = store2.get("thr-1")
    assert rec2 is not None
    assert rec2.session_id == "sess-A"
    assert rec2.turn_count == 1


def test_session_store_increments_turn_count(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    first = store.record_success("thr-1", "sess-A")
    time.sleep(0.01)  # ensure last_used_at advances
    second = store.record_success("thr-1", "sess-A")
    assert second.turn_count == 2
    assert second.first_seen_at == first.first_seen_at
    assert second.last_used_at >= first.last_used_at


def test_session_store_handles_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "sessions.json").write_text("{not json")
    store = SessionStore(tmp_path)
    # Doesn't raise — starts fresh.
    assert list(store) == []


def test_invalidate_removes_mapping(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record_success("thr-1", "sess-A")
    assert store.invalidate("thr-1") is True
    assert store.get("thr-1") is None
    # Invalidating a missing thread is a no-op signaled by False.
    assert store.invalidate("thr-1") is False


def test_prune_drops_old_sessions(tmp_path: Path) -> None:
    # Construct sessions.json with one fresh and one ancient session.
    ancient_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh_iso = datetime.now(timezone.utc).isoformat()
    (tmp_path / "sessions.json").write_text(json.dumps({
        "thr-old": {"session_id": "x", "last_used_at": ancient_iso,
                    "turn_count": 5, "first_seen_at": ancient_iso},
        "thr-new": {"session_id": "y", "last_used_at": fresh_iso,
                    "turn_count": 1, "first_seen_at": fresh_iso},
    }))
    store = SessionStore(tmp_path)
    removed = store.prune(older_than_days=14)
    assert removed == ["thr-old"]
    assert store.get("thr-new") is not None
    assert store.get("thr-old") is None


def test_is_session_fresh_age_threshold() -> None:
    rec = SessionRecord(
        session_id="x",
        last_used_at=(datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
        turn_count=3,
        first_seen_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
    )
    assert is_session_fresh(rec, max_age_days=7, max_turns=50) is False
    assert is_session_fresh(rec, max_age_days=14, max_turns=50) is True


def test_is_session_fresh_turn_threshold() -> None:
    fresh_iso = datetime.now(timezone.utc).isoformat()
    rec = SessionRecord(session_id="x", last_used_at=fresh_iso,
                        turn_count=99, first_seen_at=fresh_iso)
    assert is_session_fresh(rec, max_age_days=7, max_turns=50) is False
    assert is_session_fresh(rec, max_age_days=7, max_turns=200) is True


def test_session_store_atomic_write_does_not_leak_temp(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record_success("thr-1", "sess-A")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp.")]
    assert leftovers == []
