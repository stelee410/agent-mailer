"""Thread → claude session_id mapping (SPEC §11).

Persists `sessions.json` in the workdir's .agent-mailer/. Atomic writes,
freshness predicate per §11.2, and prune helpers for the
`agent-mailer sessions` subcommands.

Important invariant (SPEC §15.6 #2): callers must only `record_success`
AFTER claude has cleanly written its session output. A failed / killed /
unparseable claude run must NOT update the map — otherwise we'd point at
a session that doesn't actually contain the relevant turn.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(s: str) -> datetime:
    # Tolerate "Z" suffix (Claude sometimes emits that style).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class SessionRecord:
    session_id: str
    last_used_at: str
    turn_count: int
    first_seen_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "last_used_at": self.last_used_at,
            "turn_count": self.turn_count,
            "first_seen_at": self.first_seen_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionRecord":
        return cls(
            session_id=str(data["session_id"]),
            last_used_at=str(data.get("last_used_at", _now_iso())),
            turn_count=int(data.get("turn_count", 0) or 0),
            first_seen_at=str(data.get("first_seen_at", data.get("last_used_at", _now_iso()))),
        )

    def age(self, now: Optional[datetime] = None) -> timedelta:
        ref = now or _now()
        return ref - _parse_iso(self.last_used_at)


def is_session_fresh(
    rec: SessionRecord,
    *,
    max_age_days: int,
    max_turns: int,
    now: Optional[datetime] = None,
) -> bool:
    """SPEC §11.2: freshness window (default 7 days, 50 turns)."""
    if max_age_days <= 0 or max_turns <= 0:
        return False
    return (
        rec.age(now=now) < timedelta(days=max_age_days)
        and rec.turn_count < max_turns
    )


class SessionStore:
    """Read/write thread→session map. Lazy load, atomic write."""

    def __init__(self, cfg_dir: Path):
        self.path = cfg_dir / "sessions.json"
        self._loaded: Optional[dict[str, SessionRecord]] = None

    def _load(self) -> dict[str, SessionRecord]:
        if self._loaded is not None:
            return self._loaded
        if not self.path.exists():
            self._loaded = {}
            return self._loaded
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            # Corrupt sessions.json: don't crash the watcher — start fresh and
            # let it overwrite. Old data will be lost; this is acceptable
            # vs. wedging on every startup.
            self._loaded = {}
            return self._loaded
        if not isinstance(data, dict):
            self._loaded = {}
            return self._loaded
        out: dict[str, SessionRecord] = {}
        for thread_id, rec in data.items():
            if isinstance(rec, dict) and "session_id" in rec:
                try:
                    out[thread_id] = SessionRecord.from_dict(rec)
                except (KeyError, ValueError, TypeError):
                    continue
        self._loaded = out
        return out

    def get(self, thread_id: str) -> Optional[SessionRecord]:
        return self._load().get(thread_id)

    def __iter__(self) -> Iterator[tuple[str, SessionRecord]]:
        return iter(self._load().items())

    def __contains__(self, thread_id: str) -> bool:
        return thread_id in self._load()

    def items(self) -> list[tuple[str, SessionRecord]]:
        return sorted(self._load().items(), key=lambda kv: kv[1].last_used_at, reverse=True)

    def record_success(self, thread_id: str, session_id: str) -> SessionRecord:
        """Write/update mapping after a successful claude run.

        Increments turn_count if the thread already existed, preserves
        first_seen_at, and refreshes last_used_at. Persists atomically.
        """
        store = self._load()
        existing = store.get(thread_id)
        now = _now_iso()
        if existing is None:
            rec = SessionRecord(
                session_id=session_id,
                last_used_at=now,
                turn_count=1,
                first_seen_at=now,
            )
        else:
            rec = SessionRecord(
                session_id=session_id,
                last_used_at=now,
                turn_count=existing.turn_count + 1,
                first_seen_at=existing.first_seen_at,
            )
        store[thread_id] = rec
        self._persist(store)
        return rec

    def invalidate(self, thread_id: str) -> bool:
        store = self._load()
        if thread_id in store:
            del store[thread_id]
            self._persist(store)
            return True
        return False

    def prune(self, *, older_than_days: int) -> list[str]:
        """Remove records whose last_used_at is older than the cutoff.

        Returns the list of removed thread_ids.
        """
        if older_than_days <= 0:
            return []
        cutoff = _now() - timedelta(days=older_than_days)
        store = self._load()
        removed: list[str] = []
        for tid, rec in list(store.items()):
            try:
                if _parse_iso(rec.last_used_at) < cutoff:
                    del store[tid]
                    removed.append(tid)
            except ValueError:
                # Bad timestamp: treat as ancient and prune.
                del store[tid]
                removed.append(tid)
        if removed:
            self._persist(store)
        return removed

    def _persist(self, store: dict[str, SessionRecord]) -> None:
        payload = {tid: rec.to_dict() for tid, rec in store.items()}
        body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".tmp.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # sessions.json may name claude session UUIDs; not as sensitive as the
        # api_key, but the parent dir is 0700 anyway. No extra chmod needed.
        self._loaded = store
