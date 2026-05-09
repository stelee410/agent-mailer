"""Implementation of `agent-mailer verify`."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.broker import BrokerClient, PermanentBrokerError, TransientBrokerError
from agent_mailer_cli.config import ConfigError, load_config


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
    missing = cfg.missing_runtime_fields()
    if missing:
        click.echo(f"❌ config.toml is incomplete: missing {missing}", err=True)
        return 2
    return asyncio.run(_verify(cfg.broker_url, cfg.api_key, cfg.agent_id))


async def _verify(broker_url: str, api_key: str, agent_id: str) -> int:
    try:
        async with BrokerClient(broker_url, api_key, timeout=10) as client:
            data = await client.verify_agent(agent_id)
    except PermanentBrokerError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    except TransientBrokerError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 3
    click.echo(f"✓ api_key valid; broker reports agent {data.get('name', '?')!r}.")
    return 0
