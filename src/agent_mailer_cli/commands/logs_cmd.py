"""`agent-mailer logs --tail N --grep PATTERN` (SPEC §14.3)."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, load_config


def run(workdir: Optional[Path], *, tail_n: int, pattern: Optional[str]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    if cfg is None:
        click.echo(f"❌ No config.toml at {workdir_path / '.agent-mailer'}", err=True)
        return 2

    log_path = workdir_path / ".agent-mailer" / "log.jsonl"
    if not log_path.exists():
        click.echo(f"(no log.jsonl at {log_path})")
        return 0

    if tail_n <= 0:
        tail_n = 1
    matched: deque[str] = deque(maxlen=tail_n)
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if pattern is not None and pattern not in line:
                continue
            matched.append(line)
    for line in matched:
        click.echo(line)
    return 0
