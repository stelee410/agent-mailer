"""`agent-mailer sessions {list,show,invalidate,prune}` (SPEC §16.5)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, load_config
from agent_mailer_cli.sessions import SessionStore, _parse_iso, is_session_fresh

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([dhm]?)\s*$")


def _resolve_workdir_and_store(workdir: Optional[Path]) -> tuple[Path, SessionStore, "object"]:
    """Common: load config (so we can show fresh/stale), build a SessionStore."""
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(2)
    if cfg is None:
        click.echo(
            f"❌ No config.toml at {workdir_path / '.agent-mailer'}; "
            f"run `agent-mailer init` first.",
            err=True,
        )
        raise SystemExit(2)
    cfg.workdir = workdir_path
    store = SessionStore(cfg.cfg_dir)
    return workdir_path, store, cfg


def _format_age(last_used_iso: str) -> str:
    try:
        last = _parse_iso(last_used_iso)
    except ValueError:
        return "?"
    delta = datetime.now(timezone.utc) - last
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def list_sessions(workdir: Optional[Path]) -> int:
    _, store, cfg = _resolve_workdir_and_store(workdir)
    items = store.items()
    if not items:
        click.echo("(no sessions recorded yet)")
        return 0
    header = f"{'thread_id':<40}  {'session_id':<36}  {'turns':>5}  {'age':>6}  fresh"
    click.echo(header)
    click.echo("-" * len(header))
    for thread_id, rec in items:
        fresh = is_session_fresh(
            rec,
            max_age_days=cfg.session_max_age_days,
            max_turns=cfg.session_max_turns,
        )
        click.echo(
            f"{thread_id:<40}  {rec.session_id:<36}  "
            f"{rec.turn_count:>5}  {_format_age(rec.last_used_at):>6}  "
            f"{'yes' if fresh else 'no'}"
        )
    return 0


def show_session(workdir: Optional[Path], thread_id: str) -> int:
    _, store, cfg = _resolve_workdir_and_store(workdir)
    rec = store.get(thread_id)
    if rec is None:
        click.echo(f"❌ no session for thread_id={thread_id!r}", err=True)
        return 2
    fresh = is_session_fresh(
        rec,
        max_age_days=cfg.session_max_age_days,
        max_turns=cfg.session_max_turns,
    )
    click.echo(f"thread_id      = {thread_id}")
    click.echo(f"session_id     = {rec.session_id}")
    click.echo(f"turn_count     = {rec.turn_count}")
    click.echo(f"first_seen_at  = {rec.first_seen_at}")
    click.echo(f"last_used_at   = {rec.last_used_at}  (age {_format_age(rec.last_used_at)})")
    click.echo(f"fresh          = {fresh}  "
               f"(thresholds: max_age_days={cfg.session_max_age_days}, "
               f"max_turns={cfg.session_max_turns})")
    return 0


def invalidate_session(workdir: Optional[Path], thread_id: str) -> int:
    _, store, _ = _resolve_workdir_and_store(workdir)
    if store.invalidate(thread_id):
        click.echo(f"✓ removed mapping for thread_id={thread_id}")
        return 0
    click.echo(f"❌ no mapping for thread_id={thread_id}", err=True)
    return 2


def prune_sessions(workdir: Optional[Path], older_than: str) -> int:
    days = _parse_duration_to_days(older_than)
    if days is None:
        click.echo(
            f"❌ --older-than must look like '14d' / '30d' / '720h'; got {older_than!r}",
            err=True,
        )
        return 2
    _, store, _ = _resolve_workdir_and_store(workdir)
    removed = store.prune(older_than_days=days)
    if not removed:
        click.echo(f"(no sessions older than {days} days)")
        return 0
    click.echo(f"✓ pruned {len(removed)} session(s):")
    for tid in removed:
        click.echo(f"  - {tid}")
    return 0


def _parse_duration_to_days(spec: str) -> Optional[int]:
    """Accept '14d' (days), '720h' (hours), or bare number = days."""
    m = _DURATION_RE.match(spec)
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2) or "d"
    if unit == "d":
        return value
    if unit == "h":
        return max(1, value // 24)
    if unit == "m":
        # minutes — round up to 1 day for prune purposes.
        return max(1, value // 1440)
    return None
