"""Implementation of `agent-mailer fetch <msg_id>` (debug helper)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.broker import BrokerClient, PermanentBrokerError, TransientBrokerError
from agent_mailer_cli.config import ConfigError, load_config


def run(workdir: Optional[Path], msg_id: str) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    if cfg is None:
        click.echo(f"❌ No config.toml in {workdir_path}", err=True)
        return 2
    cfg.workdir = workdir_path
    if cfg.missing_runtime_fields():
        click.echo(f"❌ config.toml incomplete: {cfg.missing_runtime_fields()}", err=True)
        return 2
    return asyncio.run(_fetch(cfg.broker_url, cfg.api_key, msg_id))


async def _fetch(broker_url: str, api_key: str, msg_id: str) -> int:
    try:
        async with BrokerClient(broker_url, api_key) as client:
            data = await client.fetch_message(msg_id)
    except PermanentBrokerError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    except TransientBrokerError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 3
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    return 0
