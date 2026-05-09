"""Implementation of `agent-mailer init`."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import ConfigError
from agent_mailer_cli.security import ensure_gitignore, fix_permissions
from agent_mailer_cli.wizard import WizardAborted, run_wizard


def run(
    *,
    workdir: Optional[Path],
    no_interactive: bool,
    api_key: Optional[str],
    permission_mode: Optional[str],
    broker_url: Optional[str],
    agent_id: Optional[str],
    address: Optional[str],
    agent_name: Optional[str],
) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    cli_overrides: dict[str, object] = {
        "api_key": api_key,
        "permission_mode": permission_mode,
        "broker_url": broker_url,
        "agent_id": agent_id,
        "address": address,
        "agent_name": agent_name,
    }
    try:
        cfg = run_wizard(workdir_path, cli_overrides, no_interactive=no_interactive)
    except WizardAborted as exc:
        if str(exc):
            click.echo(f"❌ {exc}", err=True)
        return 2
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2

    fix_permissions(workdir_path)
    ensure_gitignore(workdir_path)
    click.echo(f"\n✓ Ready. Run `agent-mailer watch` from {workdir_path} to start.")
    return 0
