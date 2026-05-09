"""Implementation of `agent-mailer watch`."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError, config_file_path
from agent_mailer_cli.consistency import check_agent_id_consistency
from agent_mailer_cli.security import (
    SecurityError,
    check_workdir_security,
    ensure_gitignore,
    gitignore_covers,
    watcher_lock,
)
from agent_mailer_cli.watch import WatchAborted, watch_loop
from agent_mailer_cli.wizard import WizardAborted, run_wizard


def run(
    *,
    workdir: Optional[Path],
    broker_url: Optional[str],
    api_key: Optional[str],
    agent_id: Optional[str],
    address: Optional[str],
    permission_mode: Optional[str],
    poll_interval_idle: Optional[int],
    poll_interval_active: Optional[int],
    max_retries: Optional[int],
    no_interactive: bool,
    dry_run: bool,
    ignore_agent_md_mismatch: bool = False,
) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    cli_overrides: dict[str, object] = {
        "broker_url": broker_url,
        "api_key": api_key,
        "agent_id": agent_id,
        "address": address,
        "permission_mode": permission_mode,
        "poll_interval_idle": poll_interval_idle,
        "poll_interval_active": poll_interval_active,
        "max_retries": max_retries,
    }

    # Security check runs BEFORE the wizard for two reasons:
    # 1. The wizard's save_config rewrites the file at 0600, which would mask a
    #    pre-existing lax-permissions condition (acceptance #2).
    # 2. We don't want a running watcher to ever read credentials from a
    #    world-readable file, full stop. If config.toml is missing entirely,
    #    skip this check — the wizard will create it with strict perms.
    if config_file_path(workdir_path).exists():
        try:
            check_workdir_security(workdir_path)
        except SecurityError as exc:
            click.echo(f"❌ {exc}", err=True)
            return 2

    try:
        cfg = run_wizard(workdir_path, cli_overrides, no_interactive=no_interactive)
    except WizardAborted as exc:
        if str(exc):
            click.echo(f"❌ {exc}", err=True)
        return 2
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2

    if cfg.workdir is None:
        cfg.workdir = workdir_path

    # Re-check after wizard in case the wizard wrote a fresh config.
    try:
        check_workdir_security(workdir_path)
    except SecurityError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2

    # SPEC §15.6 invariant #5: AGENT.md ↔ config.toml agent_id must match.
    consistency = check_agent_id_consistency(workdir_path, cfg)
    if not consistency.ok:
        if ignore_agent_md_mismatch:
            click.echo(
                f"⚠️  --ignore-agent-md-mismatch set; bypassing the SPEC §15.6 "
                f"check.\n{consistency.detail}",
                err=True,
            )
        else:
            click.echo(f"❌ {consistency.detail}", err=True)
            return 2

    if not gitignore_covers(workdir_path) and (workdir_path / ".git").exists():
        click.echo(
            f"⚠️  {workdir_path / '.gitignore'} doesn't ignore .agent-mailer/ — "
            f"your API key may leak. Adding it now."
        )
        ensure_gitignore(workdir_path)

    if not cfg.permission_mode:
        click.echo("❌ permission_mode missing after wizard — aborting.", err=True)
        return 2

    try:
        with watcher_lock(workdir_path):
            return asyncio.run(watch_loop(cfg, dry_run=dry_run))
    except SecurityError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    except WatchAborted as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    except KeyboardInterrupt:
        click.echo("\n⏹  Interrupted; exiting cleanly.")
        return 130
