"""`agent-mailer team init` — provision a 4-role agent team in this directory."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import httpx

from agent_mailer_cli import team_setup
from agent_mailer_cli.team_setup import (
    COMING_SOON_FRAMEWORKS,
    DEFAULT_BROKER_URL,
    ROLES,
    SUPPORTED_FRAMEWORKS,
    TeamSetupError,
    check_empty_dir,
    create_agent,
    fetch_agent_setup,
    finalize_role,
    is_valid_team_slug,
    login,
    slugify_team,
    system_prompt_for,
    write_identity_files,
    write_partial_credentials,
    write_runtime_settings,
    write_start_script,
    write_team_meta,
)


_FRAMEWORK_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "infiniti": "Infiniti-Agent",
    "openclaw": "OpenClaw (即将支持)",
    "dreamfactory": "Dreamfactory (即将支持)",
}


def run(
    workdir: Path,
    *,
    broker_url: Optional[str] = None,
    username: Optional[str] = None,
    permission_mode: str = "bypassPermissions",
    project_dir: Optional[str] = None,
) -> int:
    """Entry point used by main.py. Returns process exit code."""
    workdir = workdir.resolve()
    try:
        check_empty_dir(workdir)
    except TeamSetupError as exc:
        click.echo(f"✖ {exc}", err=True)
        click.echo(
            "  `agent-mailer team init` requires an empty directory "
            "(.git / .DS_Store / IDE files are fine).",
            err=True,
        )
        return 1

    click.echo(click.style("agent-mailer team init", bold=True, fg="cyan"))
    click.echo(click.style(f"workdir: {workdir}", dim=True))

    resolved_broker = broker_url or os.environ.get(
        "AMP_TEAM_BROKER_URL", DEFAULT_BROKER_URL
    )

    team = _prompt_team_slug(workdir)
    frameworks = _prompt_frameworks()
    creds = _prompt_login(username)

    if permission_mode == "bypassPermissions" and not _confirm_unsandboxed_auto(frameworks):
        click.echo(
            "Aborted — re-run with --permission-mode acceptEdits or plan "
            "if you want gated execution.",
            err=True,
        )
        return 1

    try:
        with httpx.Client(timeout=60.0) as client:
            return provision_team(
                client,
                workdir,
                broker_url=resolved_broker,
                team=team,
                frameworks=frameworks,
                username=creds["username"],
                password=creds["password"],
                permission_mode=permission_mode,
                project_dir=project_dir,
            )
    except httpx.HTTPError as exc:
        click.echo(f"✖ broker not reachable: {exc}", err=True)
        return 3


def provision_team(
    client: httpx.Client,
    workdir: Path,
    *,
    broker_url: str,
    team: str,
    frameworks: dict[str, str],
    username: str,
    password: str,
    permission_mode: str = "bypassPermissions",
    project_dir: Optional[str] = None,
) -> int:
    """Network-touching half of team init. Pulled out for tests (MockTransport)."""
    workdir = workdir.resolve()
    try:
        token = login(client, broker_url, username, password)
    except TeamSetupError as exc:
        click.echo(f"✖ {exc}", err=True)
        return 4

    click.echo(
        f"\n{click.style('✓', fg='green')} logged in as "
        f"{click.style(username, bold=True)}"
    )
    click.echo(click.style(f"broker: {broker_url}\n", dim=True))

    team_meta: dict[str, object] = {
        "team_name": team,
        "username": username,
        "broker_url": broker_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "partial": False,
        "agents": [],
    }
    agents_meta: list[dict[str, object]] = []

    for role in ROLES:
        framework = frameworks[role]
        click.echo(
            f"→ creating {click.style(role, bold=True)} agent "
            f"{click.style(f'({_FRAMEWORK_LABELS[framework]})', dim=True)}..."
        )

        try:
            agent = create_agent(
                client,
                broker_url,
                token,
                name=f"{team}-{role}",
                role=role,
                description=f"{role.capitalize()} for team {team}",
                system_prompt=system_prompt_for(role, team),
            )
        except TeamSetupError as exc:
            team_meta["partial"] = True
            team_meta["failure"] = {
                "role": role,
                "error": str(exc),
                "completed_roles": [a["role"] for a in agents_meta],
            }
            team_meta["agents"] = agents_meta
            write_team_meta(workdir, team_meta)
            click.echo(
                f"{click.style('✖', fg='red')} broker rejected create for "
                f"{role}: {exc}",
                err=True,
            )
            return 2

        # P1-3 invariant: persist credentials BEFORE any fallible follow-up
        # (setup fetch, identity file write). The partial_setup_pending
        # marker file flags the role as not-yet-complete.
        write_partial_credentials(
            workdir,
            role,
            framework,
            agent,
            broker_url,
            project_dir=project_dir or "",
            permission_mode=permission_mode,
        )
        write_runtime_settings(workdir, role, framework)

        try:
            setup_resp = fetch_agent_setup(
                client,
                broker_url,
                agent["id"],
                agent["api_key_plaintext"],
            )
        except TeamSetupError as exc:
            team_meta["partial"] = True
            team_meta["failure"] = {
                "role": role,
                "error": f"setup fetch failed: {exc}",
                "completed_roles": [a["role"] for a in agents_meta],
            }
            agents_meta.append({
                "role": role,
                "id": agent["id"],
                "address": agent["address"],
                "framework": framework,
                "partial_setup_pending": True,
            })
            team_meta["agents"] = agents_meta
            write_team_meta(workdir, team_meta)
            click.echo(
                f"{click.style('✖', fg='red')} could not fetch "
                f"/agents/{agent['id']}/setup: {exc}",
                err=True,
            )
            click.echo(
                click.style(
                    f"  credentials saved to {role}/.agent-mailer/config.toml "
                    f"(partial_setup_pending marker set) — re-run team init "
                    f"or set up manually to recover.",
                    dim=True,
                ),
                err=True,
            )
            return 2

        write_identity_files(workdir, role, framework, setup_resp)
        finalize_role(workdir, role)
        write_start_script(workdir, role)

        agents_meta.append({
            "role": role,
            "id": agent["id"],
            "address": agent["address"],
            "framework": framework,
        })
        short_id = agent["id"][:8]
        click.echo(
            f"  {click.style('✓', fg='green')} {agent['address']} "
            f"{click.style(f'(id {short_id}…)', dim=True)}"
        )

    team_meta["agents"] = agents_meta
    write_team_meta(workdir, team_meta)

    click.echo(
        f"\n{click.style('done.', bold=True, fg='green')} "
        f"{len(ROLES)} agents registered, {len(ROLES)} workdirs ready.\n"
    )
    click.echo("Next:")
    for role in ROLES:
        framework = frameworks[role]
        click.echo(
            f"  {click.style(f'./start-{role}.sh', fg='cyan')}  "
            f"{click.style(f'# `agent-mailer watch` as {_FRAMEWORK_LABELS[framework]}', dim=True)}"
        )
    return 0


# ---------- interactive prompts ----------


def _confirm_unsandboxed_auto(frameworks: dict[str, str]) -> bool:
    """v0.2.x P0-1 (option B): explicit confirm before fully unsandboxed auto-execution.

    Default permission_mode `bypassPermissions` now disables BOTH approval
    gates and (for codex) the sandbox. Reviewer flagged that the codex side
    was not previously surfaced to the user — confirm step makes the full
    blast radius explicit, covering claude AND codex.
    """
    runtimes = set(frameworks.values())
    lines = ["\n⚠️  About to enable fully unsandboxed auto-execution:"]
    if "claude" in runtimes:
        lines.append(
            "  - claude roles: --dangerously-skip-permissions "
            "(all approval gates off)"
        )
    if "codex" in runtimes:
        lines.append(
            "  - codex roles: --dangerously-bypass-approvals-and-sandbox "
            "(sandbox OFF, raw shell)"
        )
    if "infiniti" in runtimes:
        lines.append(
            "  - infiniti roles: runtime has no approval gate by design"
        )
    lines += [
        "This lets `agent-mailer watch` handle every incoming email without",
        "prompts, but spawned processes can run any shell command, read any",
        "file, and reach any network. Recommended only for trusted workdirs.",
        "",
    ]
    click.echo(click.style("\n".join(lines), fg="yellow"))
    return click.confirm(
        "Enable fully unsandboxed auto-execution?",
        default=True,
    )


def _prompt_team_slug(workdir: Path) -> str:
    default = slugify_team(workdir.name) or "team"
    while True:
        raw = click.prompt(
            "Team name (used as agent address prefix)",
            default=default,
            show_default=True,
        )
        slug = slugify_team(raw)
        if is_valid_team_slug(slug):
            return slug
        click.echo(
            "  ✖ must start and end with a letter or digit; allowed middle: . _ -",
            err=True,
        )


def _prompt_frameworks() -> dict[str, str]:
    out: dict[str, str] = {}
    for role in ROLES:
        out[role] = _prompt_one_framework(role)
    return out


def _prompt_one_framework(role: str) -> str:
    menu = (
        f"\nAgent framework for {click.style(role, bold=True)}:\n"
        "  [1] Claude Code\n"
        "  [2] Codex\n"
        "  [3] Infiniti-Agent\n"
        "  [4] OpenClaw (即将支持)\n"
        "  [5] Dreamfactory (即将支持)"
    )
    aliases = {
        "1": "claude", "claude": "claude",
        "2": "codex", "codex": "codex",
        "3": "infiniti", "infiniti": "infiniti", "infiniti-agent": "infiniti",
        "4": "openclaw", "openclaw": "openclaw",
        "5": "dreamfactory", "dreamfactory": "dreamfactory",
    }
    while True:
        click.echo(menu)
        choice = click.prompt("> ", type=str, default="1").strip().lower()
        normalized = aliases.get(choice)
        if normalized in SUPPORTED_FRAMEWORKS:
            return normalized
        if normalized in COMING_SOON_FRAMEWORKS:
            click.echo(
                click.style(
                    f"  ✖ {normalized} 即将支持，请选 Claude Code / Codex / Infiniti-Agent",
                    fg="red",
                ),
                err=True,
            )
            continue
        click.echo(
            click.style("  ✖ please enter 1-5 or one of the framework names", fg="red"),
            err=True,
        )


def _prompt_login(default_username: Optional[str]) -> dict[str, str]:
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        username = click.prompt(
            "amp.linkyun.co username",
            default=default_username or os.environ.get("AMP_USERNAME"),
            show_default=bool(default_username or os.environ.get("AMP_USERNAME")),
        ).strip()
        if not username:
            click.echo("  ✖ username is required", err=True)
            continue
        password = click.prompt("password", hide_input=True, default="", show_default=False)
        if not password:
            click.echo("  ✖ password is required", err=True)
            continue
        return {"username": username, "password": password}
    raise click.ClickException("too many empty login attempts")
