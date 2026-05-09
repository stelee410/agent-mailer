"""`agent-mailer status` (SPEC §14.3)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, load_config
from agent_mailer_cli.recovery import DeadLetterStore
from agent_mailer_cli.state import LocalState


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists, owned by another user. Treat as alive.
        return True
    return True


def _read_lock_pid(cfg_dir: Path) -> Optional[int]:
    lock = cfg_dir / ".lock"
    if not lock.exists():
        return None
    try:
        text = lock.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("pid="):
        return None
    try:
        return int(text.split("=", 1)[1])
    except (ValueError, IndexError):
        return None


def run(workdir: Optional[Path]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    if cfg is None:
        click.echo(f"❌ No config.toml at {workdir_path / '.agent-mailer'}", err=True)
        return 2
    cfg.workdir = workdir_path

    click.echo(f"workdir:        {workdir_path}")
    click.echo(f"agent:          {cfg.agent_name}  ({cfg.address})")
    click.echo(f"broker:         {cfg.broker_url}")

    pid = _read_lock_pid(cfg.cfg_dir)
    if pid is None:
        click.echo("watcher:        not running (no .agent-mailer/.lock)")
    elif _is_pid_alive(pid):
        click.echo(f"watcher:        running (pid {pid})")
    else:
        click.echo(f"watcher:        stale lock (pid {pid} not alive — "
                   f"safe to remove .agent-mailer/.lock if you've confirmed)")

    state = LocalState(cfg.cfg_dir)
    click.echo(f"processed:      {len(state.processed)} message(s)")
    click.echo(f"cursor:         {state.cursor or '(none)'}")
    inflight = state.load_inflight()
    if inflight is None:
        click.echo("inflight:       none")
    else:
        click.echo(
            f"inflight:       msg_id={inflight.msg_id}  "
            f"thread_id={inflight.thread_id}  started_at={inflight.started_at}"
        )

    dead = DeadLetterStore(cfg.cfg_dir).all_records()
    click.echo(f"dead_letter:    {len(dead)} record(s)")

    last_event = _last_log_event(state.log_path)
    if last_event:
        click.echo(f"last_log_event: {last_event}")
    return 0


def _last_log_event(log_path: Path) -> Optional[str]:
    if not log_path.exists():
        return None
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            chunk_size = min(size, 4096)
            fh.seek(size - chunk_size)
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    last_line = ""
    for line in tail.splitlines():
        if line.strip():
            last_line = line
    if not last_line:
        return None
    try:
        rec = json.loads(last_line)
    except json.JSONDecodeError:
        return last_line[:200]
    ts = rec.get("ts", "?")
    event = rec.get("event", "?")
    return f"{ts}  {event}"
