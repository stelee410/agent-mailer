"""`agent-mailer dead-letter {list,retry,purge}` (SPEC §16.4)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, load_config
from agent_mailer_cli.recovery import DeadLetterStore, RetryStore
from agent_mailer_cli.state import LocalState


def _resolve(workdir: Optional[Path]):
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
    return workdir_path, cfg


def list_dead_letter(workdir: Optional[Path]) -> int:
    _, cfg = _resolve(workdir)
    store = DeadLetterStore(cfg.cfg_dir)
    records = store.all_records()
    if not records:
        click.echo("(dead_letter.jsonl is empty)")
        return 0
    header = f"{'msg_id':<40}  {'thread_id':<40}  {'retries':>7}  stuck_at"
    click.echo(header)
    click.echo("-" * len(header))
    for r in records:
        click.echo(f"{r.msg_id:<40}  {r.thread_id:<40}  {r.retries:>7}  {r.stuck_at}")
    return 0


def retry_dead_letter(workdir: Optional[Path], msg_id: str) -> int:
    _, cfg = _resolve(workdir)
    store = DeadLetterStore(cfg.cfg_dir)
    rec = store.remove(msg_id)
    if rec is None:
        click.echo(f"❌ no record in dead_letter.jsonl for msg_id={msg_id!r}", err=True)
        return 2
    # Also clear processed.txt entry so the next poll picks it up again, and
    # reset the retry counter.
    state = LocalState(cfg.cfg_dir)
    if msg_id in state.processed:
        # processed.txt is line-based; rewrite without this id.
        survivors = [m for m in state.processed if m != msg_id]
        state.processed_path.write_text("\n".join(survivors) + ("\n" if survivors else ""),
                                        encoding="utf-8")
        state._processed = set(survivors)  # noqa: SLF001 — invalidate cache
    RetryStore(cfg.cfg_dir).clear(msg_id)
    click.echo(f"✓ {msg_id} moved out of dead-letter; will be retried on next poll "
               f"(was: {rec.retries} retries, last_error: {rec.last_error[:120]!r})")
    return 0


def purge_dead_letter(workdir: Optional[Path]) -> int:
    _, cfg = _resolve(workdir)
    store = DeadLetterStore(cfg.cfg_dir)
    count = store.purge()
    if count == 0:
        click.echo("(dead_letter.jsonl already empty)")
    else:
        click.echo(f"✓ purged {count} record(s) from dead_letter.jsonl")
    return 0
