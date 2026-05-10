"""`agent-mailer memory {show,edit,ls}` (SPEC §16.6)."""
from __future__ import annotations

import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, load_config
from agent_mailer_cli.memory import (
    ensure_global_md,
    global_md_path,
    list_memory_files,
    memory_dir,
    thread_md_path,
)


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


def show(workdir: Optional[Path], thread: Optional[str]) -> int:
    workdir_path, cfg = _resolve(workdir)
    if thread:
        path = thread_md_path(workdir_path, thread)
    else:
        # Lazy-create global.md if it doesn't exist yet so `memory show`
        # always has something to print after `init`.
        path = ensure_global_md(workdir_path, agent_name=cfg.agent_name)
    if not path.exists():
        click.echo(f"❌ {path} does not exist (no notes yet for this thread).", err=True)
        return 2
    click.echo(f"# {path}")
    click.echo(path.read_text(encoding="utf-8"))
    return 0


def edit(workdir: Optional[Path], thread: Optional[str]) -> int:
    workdir_path, cfg = _resolve(workdir)
    if thread:
        path = thread_md_path(workdir_path, thread)
        if not path.exists():
            # Auto-create empty per-thread file so $EDITOR has something to open.
            from agent_mailer_cli.memory import ensure_memory_dir
            ensure_memory_dir(workdir_path)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fdopen(fd, "w").write(f"# Thread {thread} Handoff Notes\n\n")
    else:
        path = ensure_global_md(workdir_path, agent_name=cfg.agent_name)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    cmd = shlex.split(editor) + [str(path)]
    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        click.echo(f"❌ Editor not found: {editor!r}", err=True)
        return 2
    return result.returncode


def ls(workdir: Optional[Path]) -> int:
    workdir_path, _ = _resolve(workdir)
    md = memory_dir(workdir_path)
    files = list_memory_files(workdir_path)
    if not files:
        click.echo(f"(no memory files in {md})")
        return 0
    click.echo(f"# {md}")
    for f in files:
        st = f.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        click.echo(f"{f.name:<40}  {st.st_size:>8} bytes  {mtime}")
    return 0
