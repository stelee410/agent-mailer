"""Local watcher state: processed.txt, inflight.json, cursor.txt, log.jsonl.

All writes are atomic: write to a temp file in the same directory, fsync,
rename. processed.txt and cursor.txt are pure text; inflight.json is a
single small JSON object. The state machine is small enough that we don't
need an embedded DB.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class InflightRecord:
    msg_id: str
    thread_id: str
    started_at: str
    retry_count: int = 0


class LocalState:
    def __init__(self, cfg_dir: Path):
        self.cfg_dir = cfg_dir
        self.processed_path = cfg_dir / "processed.txt"
        self.inflight_path = cfg_dir / "inflight.json"
        self.cursor_path = cfg_dir / "cursor.txt"
        self.log_path = cfg_dir / "log.jsonl"
        self.dead_letter_path = cfg_dir / "dead_letter.jsonl"
        self._processed: Optional[set[str]] = None

    @property
    def processed(self) -> set[str]:
        if self._processed is None:
            self._processed = self._load_processed()
        return self._processed

    def _load_processed(self) -> set[str]:
        if not self.processed_path.exists():
            return set()
        return {
            line.strip()
            for line in self.processed_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    def add_processed(self, msg_id: str) -> None:
        if msg_id in self.processed:
            return
        self.processed.add(msg_id)
        with self.processed_path.open("a", encoding="utf-8") as fh:
            fh.write(msg_id + "\n")

    def filter_unprocessed(self, msg_ids: list[str]) -> list[str]:
        seen = self.processed
        return [m for m in msg_ids if m not in seen]

    @property
    def cursor(self) -> Optional[str]:
        if not self.cursor_path.exists():
            return None
        text = self.cursor_path.read_text(encoding="utf-8").strip()
        return text or None

    def save_cursor(self, msg_id: str) -> None:
        _atomic_write_text(self.cursor_path, msg_id + "\n")

    def load_inflight(self) -> Optional[InflightRecord]:
        if not self.inflight_path.exists():
            return None
        try:
            data = json.loads(self.inflight_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None
        return InflightRecord(
            msg_id=data["msg_id"],
            thread_id=data.get("thread_id", ""),
            started_at=data.get("started_at", ""),
            retry_count=int(data.get("retry_count", 0)),
        )

    def set_inflight(self, msg_id: str, thread_id: str, retry_count: int = 0) -> InflightRecord:
        rec = InflightRecord(msg_id=msg_id, thread_id=thread_id,
                             started_at=now_iso(), retry_count=retry_count)
        _atomic_write_text(
            self.inflight_path,
            json.dumps({
                "msg_id": rec.msg_id,
                "thread_id": rec.thread_id,
                "started_at": rec.started_at,
                "retry_count": rec.retry_count,
            }, indent=2) + "\n",
        )
        return rec

    def clear_inflight(self) -> None:
        try:
            self.inflight_path.unlink()
        except FileNotFoundError:
            pass

    def append_log(self, event: str, **fields: Any) -> None:
        record: dict[str, Any] = {"ts": now_iso(), "event": event}
        record.update(fields)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def append_dead_letter(self, msg_id: str, **fields: Any) -> None:
        record: dict[str, Any] = {"ts": now_iso(), "msg_id": msg_id}
        record.update(fields)
        with self.dead_letter_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically (write-then-rename)."""
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
