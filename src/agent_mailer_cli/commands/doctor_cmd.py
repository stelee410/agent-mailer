"""Implementation of `agent-mailer doctor`."""
from __future__ import annotations

import asyncio
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.broker import BrokerClient, PermanentBrokerError, TransientBrokerError
from agent_mailer_cli.config import config_file_path, load_config
from agent_mailer_cli.consistency import check_agent_id_consistency


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run(workdir: Optional[Path]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    checks: list[CheckResult] = []

    # 1. claude on PATH
    claude_path = shutil.which("claude")
    checks.append(CheckResult(
        "claude CLI on PATH",
        claude_path is not None,
        claude_path or "not found — install via `npm install -g @anthropic-ai/claude-code`",
    ))

    # 2. config.toml exists
    cfg_path = config_file_path(workdir_path)
    cfg_dir = cfg_path.parent
    checks.append(CheckResult(
        "config.toml exists", cfg_path.exists(),
        str(cfg_path) if cfg_path.exists() else f"missing — run `agent-mailer init`",
    ))

    # 3. permissions
    if cfg_dir.exists():
        dir_mode = cfg_dir.stat().st_mode & 0o777
        checks.append(CheckResult(
            ".agent-mailer/ permissions <= 0700",
            not (dir_mode & 0o077),
            oct(dir_mode),
        ))
    if cfg_path.exists():
        file_mode = cfg_path.stat().st_mode & 0o777
        checks.append(CheckResult(
            "config.toml permissions <= 0600",
            not (file_mode & 0o077),
            oct(file_mode),
        ))

    # 4. config completeness
    cfg = None
    if cfg_path.exists():
        try:
            cfg = load_config(workdir_path)
        except Exception as exc:
            checks.append(CheckResult("config.toml parses", False, str(exc)))
        else:
            assert cfg is not None
            cfg.workdir = workdir_path
            missing = cfg.missing_runtime_fields()
            checks.append(CheckResult(
                "config.toml has all runtime fields",
                not missing,
                "ok" if not missing else f"missing: {missing}",
            ))
            checks.append(CheckResult(
                "permission_mode set",
                bool(cfg.permission_mode),
                cfg.permission_mode or "(empty — wizard will ask on next watch)",
            ))

    # 5. broker connectivity (only if cfg complete)
    if cfg and not cfg.missing_runtime_fields():
        ok, detail = asyncio.run(_check_broker(cfg.broker_url, cfg.api_key, cfg.agent_id))
        checks.append(CheckResult("broker reachable + api_key valid", ok, detail))

    # 5b. SPEC §15.6 invariant #5: AGENT.md ↔ config.toml agent_id consistency.
    if cfg:
        consistency = check_agent_id_consistency(workdir_path, cfg)
        checks.append(CheckResult(
            "AGENT.md ↔ config.toml agent_id consistent",
            consistency.ok,
            consistency.detail.splitlines()[0] if consistency.ok else consistency.detail,
        ))

    # 6. .gitignore covers .agent-mailer/ (only if .git present)
    if (workdir_path / ".git").exists():
        from agent_mailer_cli.security import gitignore_covers
        ok = gitignore_covers(workdir_path)
        checks.append(CheckResult(
            ".gitignore covers .agent-mailer/", ok,
            "ok" if ok else "add `.agent-mailer/` to .gitignore",
        ))

    # 7. inflight
    inflight = cfg_dir / "inflight.json"
    if inflight.exists():
        checks.append(CheckResult(
            "no stale inflight", False,
            f"present: {inflight} (will be cleared on next watch)",
        ))

    failures = sum(1 for c in checks if not c.ok)
    for c in checks:
        prefix = "✓" if c.ok else "✗"
        click.echo(f"{prefix} {c.name}: {c.detail}")
    click.echo("")
    if failures:
        click.echo(f"❌ {failures} check(s) failed.", err=True)
        return 1
    click.echo("✅ All checks passed.")
    return 0


async def _check_broker(broker_url: str, api_key: str, agent_id: str) -> tuple[bool, str]:
    try:
        async with BrokerClient(broker_url, api_key, timeout=10) as client:
            data = await client.verify_agent(agent_id)
    except PermanentBrokerError as exc:
        return False, f"{exc}"
    except TransientBrokerError as exc:
        return False, f"{exc}"
    except Exception as exc:  # noqa: BLE001 — surface anything unexpected
        return False, f"unexpected error: {exc}"
    name = data.get("name", "?")
    return True, f"agent {name!r} ({agent_id}) verified"
