"""SPEC §13: retries / dead-letter / inflight crash recovery.

Two persistent files at workdir scope:
- `retries.json` — {msg_id: count} for messages we've tried and failed.
- `dead_letter.jsonl` — append-only log of msg_ids that exhausted max_retries.

Plus a `recover_inflight` helper invoked at watcher startup: if there's an
inflight.json older than the (configurable) age threshold, treat it as a
crashed turn and either bump retries or move it to dead-letter.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DEFAULT_INFLIGHT_AGE_SECONDS = 15 * 60  # §13.3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp.", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class DeadLetterRecord:
    msg_id: str
    thread_id: str
    retries: int
    last_error: str
    stuck_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "msg_id": self.msg_id,
            "thread_id": self.thread_id,
            "retries": self.retries,
            "last_error": self.last_error,
            "stuck_at": self.stuck_at,
        }


class RetryStore:
    """Persistent retry-count map.

    Lives at <workdir>/.agent-mailer/retries.json. Crash-tolerant: corrupt
    JSON resets to empty (we'd rather forget retry counts than wedge the
    watcher on every startup). Atomic write.
    """

    def __init__(self, cfg_dir: Path):
        self.path = cfg_dir / "retries.json"
        self._cache: Optional[dict[str, int]] = None

    def _load(self) -> dict[str, int]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            self._cache = {}
            return self._cache
        if not isinstance(data, dict):
            self._cache = {}
            return self._cache
        out: dict[str, int] = {}
        for k, v in data.items():
            try:
                out[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        self._cache = out
        return out

    def get(self, msg_id: str) -> int:
        return self._load().get(msg_id, 0)

    def increment(self, msg_id: str) -> int:
        store = self._load()
        store[msg_id] = store.get(msg_id, 0) + 1
        self._persist(store)
        return store[msg_id]

    def clear(self, msg_id: str) -> None:
        store = self._load()
        if msg_id in store:
            del store[msg_id]
            self._persist(store)

    def all_counts(self) -> dict[str, int]:
        return dict(self._load())

    def _persist(self, store: dict[str, int]) -> None:
        body = json.dumps(store, indent=2, sort_keys=True) + "\n"
        _atomic_write(self.path, body)
        self._cache = store


class DeadLetterStore:
    """Append-only log of messages that exhausted retries (§13.4)."""

    def __init__(self, cfg_dir: Path):
        self.path = cfg_dir / "dead_letter.jsonl"

    def append(self, rec: DeadLetterRecord) -> None:
        from agent_mailer_cli.state import _append_jsonl_secure
        _append_jsonl_secure(self.path, json.dumps(rec.to_dict()))

    def all_records(self) -> list[DeadLetterRecord]:
        if not self.path.exists():
            return []
        out: list[DeadLetterRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                out.append(DeadLetterRecord(
                    msg_id=str(d["msg_id"]),
                    thread_id=str(d.get("thread_id", "")),
                    retries=int(d.get("retries", 0)),
                    last_error=str(d.get("last_error", "")),
                    stuck_at=str(d.get("stuck_at", "")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def remove(self, msg_id: str) -> Optional[DeadLetterRecord]:
        """Move a record out of dead-letter (used by `dead-letter retry`)."""
        if not self.path.exists():
            return None
        records = self.all_records()
        target: Optional[DeadLetterRecord] = None
        keep: list[DeadLetterRecord] = []
        for r in records:
            if target is None and r.msg_id == msg_id:
                target = r
            else:
                keep.append(r)
        if target is None:
            return None
        body = "".join(json.dumps(r.to_dict()) + "\n" for r in keep)
        _atomic_write(self.path, body)
        return target

    def purge(self) -> int:
        if not self.path.exists():
            return 0
        count = sum(1 for r in self.all_records())
        if self.path.exists():
            self.path.unlink()
        return count


@dataclass
class RecoveryAction:
    """What `recover_inflight` decided. Returned for caller-side logging."""

    msg_id: Optional[str]
    action: str  # "noop", "wait", "retry", "dead_letter"
    age_seconds: float
    retry_count: int
    detail: str


def recover_inflight(
    inflight_path: Path,
    *,
    retries: RetryStore,
    dead_letter: DeadLetterStore,
    max_retries: int,
    age_threshold_seconds: int = DEFAULT_INFLIGHT_AGE_SECONDS,
) -> RecoveryAction:
    """SPEC §13.3: decide what to do about a stale inflight record.

    Returns a RecoveryAction describing the decision. Side effects:
    - For `retry`: increments retries.json and clears inflight.
    - For `dead_letter`: appends to dead_letter.jsonl, clears retries entry,
      and clears inflight.
    - For `wait`: leaves inflight intact (caller should keep polling).
    - For `noop`: nothing to recover.
    """
    if not inflight_path.exists():
        return RecoveryAction(None, "noop", 0.0, 0, "no inflight.json present")
    try:
        data = json.loads(inflight_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        # Corrupt inflight: wipe it; we'd rather drop one possible retry than
        # wedge the watcher.
        inflight_path.unlink(missing_ok=True)
        return RecoveryAction(None, "noop", 0.0, 0, "corrupt inflight.json removed")
    msg_id = str(data.get("msg_id", ""))
    thread_id = str(data.get("thread_id", ""))
    started_at = data.get("started_at", "")
    if not msg_id:
        inflight_path.unlink(missing_ok=True)
        return RecoveryAction(None, "noop", 0.0, 0, "inflight had no msg_id; cleared")
    try:
        age = (_now() - _parse_iso(started_at)).total_seconds()
    except ValueError:
        age = float("inf")  # unparseable timestamp → treat as ancient

    if age < age_threshold_seconds:
        return RecoveryAction(msg_id, "wait", age,
                              retries.get(msg_id),
                              f"inflight age {age:.0f}s < threshold {age_threshold_seconds}s; "
                              f"another watcher or claude may still be working")

    new_count = retries.increment(msg_id)
    if new_count >= max_retries:
        dead_letter.append(DeadLetterRecord(
            msg_id=msg_id, thread_id=thread_id,
            retries=new_count,
            last_error=f"inflight stale {age:.0f}s on watcher restart",
            stuck_at=_now_iso(),
        ))
        retries.clear(msg_id)
        inflight_path.unlink(missing_ok=True)
        return RecoveryAction(msg_id, "dead_letter", age, new_count,
                              f"retry budget exhausted ({new_count}/{max_retries})")

    inflight_path.unlink(missing_ok=True)
    return RecoveryAction(msg_id, "retry", age, new_count,
                          f"will retry; count now {new_count}/{max_retries}")
