"""First-run / fix-up wizard (§8.2).

Three flows:
  A — config.toml exists but missing permission_mode → ask only that.
  B — AGENT.md exists, no config.toml → confirm identity, ask api_key + permission_mode.
  C — Nothing → refuse with guidance, unless the user passed enough overrides.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import (
    VALID_PERMISSION_MODES,
    Config,
    ConfigError,
    mask_api_key,
    save_config,
)
from agent_mailer_cli.discovery import DiscoveryResult, discover
from agent_mailer_cli.security import ensure_gitignore, fix_permissions

PERMISSION_MENU = """\
Permission mode for headless Claude:
  [1] acceptEdits           Allow file edits, deny command execution.
                            (Recommended for most agents.)
  [2] bypassPermissions     No safety checks. Claude can run any command.
                            (Only for trusted automation.)
  [3] plan                  Read-only mode. Claude can only plan, not act.
                            (For review-only agents.)"""


class WizardAborted(Exception):
    pass


def run_wizard(
    workdir: Path,
    cli_overrides: dict[str, object],
    no_interactive: bool = False,
) -> Config:
    """Resolve a complete Config or raise WizardAborted/ConfigError.

    On success, the config is persisted to disk and returned with workdir set.
    """
    result = discover(workdir, **cli_overrides)
    cfg = result.config

    if not result.config_existed and result.agent_md_path is None and not _has_enough_overrides(cli_overrides):
        # Scenario C: nothing to work with.
        click.echo("\n❌ Not an agent workdir.\n", err=True)
        click.echo(
            f"This directory ({workdir}) has no AGENT.md or .agent-mailer/config.toml.\n",
            err=True,
        )
        click.echo("To set up an agent here:", err=True)
        click.echo("  1. Run: claude", err=True)
        click.echo(
            "  2. In claude: read https://amp.linkyun.co/setup.md to register your agent",
            err=True,
        )
        click.echo("  3. Exit claude, then re-run: agent-mailer watch", err=True)
        click.echo(
            "\nOr run `agent-mailer init` and pass --api-key/--agent-id/etc on the command line.",
            err=True,
        )
        raise WizardAborted()

    fully_configured = (
        result.config_existed
        and not cfg.missing_runtime_fields()
        and cfg.permission_mode in VALID_PERMISSION_MODES
    )
    if fully_configured:
        # Happy path: nothing to ask. Avoid the v1 M3 P1-2 permission-mode
        # re-prompt (its no-empty-default policy is the right default for
        # *fresh* setup, not for re-runs of an already-complete workdir).
        return cfg

    only_perm_missing = (
        result.config_existed
        and not cfg.missing_runtime_fields()
        and not cfg.permission_mode
    )

    if only_perm_missing:
        click.echo("\n🔧 Almost set up — one more question.\n")
        _print_identity_summary(cfg)
        cfg.permission_mode = _resolve_permission_mode(cli_overrides, no_interactive)
        save_config(cfg)
        click.echo(f"\n✓ Saved to {cfg.cfg_file}")
        return cfg

    # Scenarios A (with full reconfirmation) and B (fresh from AGENT.md).
    if result.config_existed:
        click.echo("\n🔧 First-time setup for this workdir\n")
        click.echo(f"Detected from {cfg.cfg_file}:")
    elif result.agent_md_path is not None:
        click.echo("\n🔧 First-time setup for this workdir\n")
        click.echo(f"Detected from {result.agent_md_path}:")
    else:
        click.echo("\n🔧 Setting up from command-line arguments.\n")

    _print_identity_summary(cfg)

    if no_interactive:
        # Headless mode: every required field must already be set.
        missing = cfg.missing_runtime_fields()
        if not cfg.permission_mode:
            missing.append("permission_mode")
        if missing:
            raise WizardAborted(
                f"--no-interactive set but these fields are unresolved: {missing}"
            )
        save_config(cfg)
        was_added, gi = ensure_gitignore(workdir)
        if was_added:
            click.echo(f"✓ Added .agent-mailer/ to {gi}")
        fix_permissions(workdir)
        click.echo(f"✓ Saved to {cfg.cfg_file}")
        return cfg

    # Interactive prompts. Prompts use the existing value as default; an empty
    # input keeps the default.
    cfg.agent_name = _prompt_str("Confirm agent name", cfg.agent_name, required=True)
    cfg.agent_id = _prompt_str("Agent ID", cfg.agent_id, required=True)
    cfg.address = _prompt_str("Address", cfg.address, required=True)
    cfg.broker_url = _prompt_str("Broker URL", cfg.broker_url, required=True)

    if cfg.api_key:
        click.echo(f"API key on file: {mask_api_key(cfg.api_key)}")
        if click.confirm("Replace it?", default=False):
            cfg.api_key = click.prompt("New API key", hide_input=True, default="").strip()
            if not cfg.api_key:
                raise WizardAborted("api_key cannot be empty")
    else:
        api_key = click.prompt("API key for this agent", hide_input=True, default="").strip()
        if not api_key:
            raise WizardAborted("api_key is required")
        cfg.api_key = api_key

    cfg.permission_mode = _resolve_permission_mode(cli_overrides, no_interactive=False, current=cfg.permission_mode)

    save_config(cfg)
    was_added, gi = ensure_gitignore(workdir)
    fix_permissions(workdir)
    click.echo(f"✓ Created {cfg.cfg_file} (mode 0600)")
    click.echo(f"✓ Created {cfg.cfg_dir}/ (mode 0700)")
    if was_added:
        click.echo(f"✓ Added .agent-mailer/ to {gi}")
    return cfg


def _has_enough_overrides(overrides: dict[str, object]) -> bool:
    needed = {"agent_id", "address", "broker_url", "api_key"}
    return all(overrides.get(k) for k in needed)


def _print_identity_summary(cfg: Config) -> None:
    click.echo(f"  Agent name:   {cfg.agent_name or '(not set)'}")
    click.echo(f"  Agent ID:     {cfg.agent_id or '(not set)'}")
    click.echo(f"  Address:      {cfg.address or '(not set)'}")
    click.echo(f"  Broker URL:   {cfg.broker_url or '(not set)'}")
    click.echo(f"  API key:      {mask_api_key(cfg.api_key) or '(not set)'}")
    click.echo("")


def _resolve_permission_mode(
    cli_overrides: dict[str, object],
    no_interactive: bool,
    current: str = "",
) -> str:
    cli_value = cli_overrides.get("permission_mode")
    if isinstance(cli_value, str) and cli_value:
        if cli_value not in VALID_PERMISSION_MODES:
            raise ConfigError(
                f"--permission-mode must be one of {VALID_PERMISSION_MODES}, got {cli_value!r}"
            )
        return cli_value
    if no_interactive:
        if current in VALID_PERMISSION_MODES:
            return current
        raise WizardAborted("permission_mode required in --no-interactive mode")

    click.echo("")
    click.echo(PERMISSION_MENU)
    # SPEC §15.6 invariant #8 / §8.3: permission_mode must be EXPLICITLY chosen.
    # No default — empty input re-prompts. This prevents silent privilege
    # escalation (e.g. current="plan" + user-Enter would otherwise default to
    # acceptEdits, broadening permissions without consent).
    while True:
        choice = click.prompt("> ", type=str, default="", show_default=False).strip()
        if not choice:
            click.echo(
                "Please enter 1, 2, or 3 — empty input is not accepted "
                "(no silent default).",
                err=True,
            )
            continue
        if choice in ("1", "acceptEdits"):
            return "acceptEdits"
        if choice in ("2", "bypassPermissions"):
            return "bypassPermissions"
        if choice in ("3", "plan"):
            return "plan"
        click.echo("Please enter 1, 2, or 3.", err=True)


def _prompt_str(label: str, default: str, required: bool) -> str:
    while True:
        value = click.prompt(label, default=default if default else "", show_default=bool(default))
        value = value.strip()
        if value or not required:
            return value
        click.echo(f"{label} is required.", err=True)
