"""Implementation of `agent-mailer test-claude` (smoke check)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.claude_runner import (
    ClaudeNotFoundError,
    ClaudeRunError,
    ClaudeTimeoutError,
    build_cmd,
    run_claude,
)
from agent_mailer_cli.config import ConfigError, load_config


def run(workdir: Optional[Path]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    if cfg is None:
        # Allow running without config — fall back to defaults.
        permission_mode = "plan"
        claude_command = "claude"
    else:
        cfg.workdir = workdir_path
        permission_mode = cfg.permission_mode or "plan"
        claude_command = cfg.claude_command or "claude"

    cmd = build_cmd(
        claude_command=claude_command,
        prompt="Say only the word 'OK' and nothing else.",
        permission_mode=permission_mode,
    )
    click.echo(f"$ {' '.join(cmd[:3])} <prompt> --output-format json --permission-mode {permission_mode}")
    try:
        result = asyncio.run(run_claude(cmd, cwd=workdir_path, timeout_seconds=120))
    except ClaudeNotFoundError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    except ClaudeTimeoutError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 3
    except ClaudeRunError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 3

    click.echo(f"return_code: {result.return_code}")
    click.echo(f"duration:    {result.duration_seconds:.1f}s")
    if result.parsed and isinstance(result.parsed, dict):
        click.echo(f"session_id:  {result.parsed.get('session_id', '?')}")
        click.echo(f"cost:        ${result.parsed.get('total_cost_usd', 0):.4f}")
        click.echo(f"result:      {result.parsed.get('result', '')[:200]}")
    elif result.parse_error:
        click.echo(f"⚠️  could not parse stdout as JSON: {result.parse_error}")
        click.echo(f"stdout (first 400 chars): {result.stdout[:400]}")
    return 0 if result.return_code == 0 else 1
