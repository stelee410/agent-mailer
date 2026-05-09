"""Top-level click entry point for the agent-mailer CLI.

The functions below are thin shells that delegate to module implementations.
Subcommand bodies that aren't part of the M0-M2 wave intentionally raise
NotImplementedError so they show up in `--help` but error loudly when invoked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli import __version__
from agent_mailer_cli.commands import (
    config_cmd,
    doctor_cmd,
    init_cmd,
    verify_cmd,
    watch_cmd,
)


@click.group(
    help=(
        "agent-mailer — Agent Mailer Protocol local runtime.\n\n"
        "Run from inside a workdir that has been registered via setup.md."
    )
)
@click.version_option(__version__, prog_name="agent-mailer")
def cli() -> None:
    pass


@cli.command("watch", help="Poll the broker inbox and spawn headless claude per message.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Workdir to operate on (default: current directory).")
@click.option("--broker-url", default=None, help="Override broker_url from config.toml.")
@click.option("--api-key", default=None, help="Override api_key from config.toml.")
@click.option("--agent-id", default=None, help="Override agent_id from config.toml.")
@click.option("--address", default=None, help="Override address from config.toml.")
@click.option("--permission-mode", type=click.Choice(["acceptEdits", "bypassPermissions", "plan"]),
              default=None, help="Override permission_mode from config.toml.")
@click.option("--poll-interval-idle", type=int, default=None, help="Override idle poll interval (s).")
@click.option("--poll-interval-active", type=int, default=None, help="Override active poll interval (s).")
@click.option("--max-retries", type=int, default=None, help="Override max_retries.")
@click.option("--no-interactive", is_flag=True, default=False,
              help="Refuse to prompt; missing fields cause exit 2.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Poll only; do not spawn claude. Useful for debugging connectivity.")
def watch(workdir: Optional[Path], broker_url: Optional[str], api_key: Optional[str],
          agent_id: Optional[str], address: Optional[str], permission_mode: Optional[str],
          poll_interval_idle: Optional[int], poll_interval_active: Optional[int],
          max_retries: Optional[int], no_interactive: bool, dry_run: bool) -> None:
    code = watch_cmd.run(
        workdir=workdir,
        broker_url=broker_url,
        api_key=api_key,
        agent_id=agent_id,
        address=address,
        permission_mode=permission_mode,
        poll_interval_idle=poll_interval_idle,
        poll_interval_active=poll_interval_active,
        max_retries=max_retries,
        no_interactive=no_interactive,
        dry_run=dry_run,
    )
    sys.exit(code)


@cli.command("init", help="Run the wizard but do not enter the watch loop.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--no-interactive", is_flag=True, default=False)
@click.option("--api-key", default=None)
@click.option("--permission-mode", type=click.Choice(["acceptEdits", "bypassPermissions", "plan"]),
              default=None)
@click.option("--broker-url", default=None)
@click.option("--agent-id", default=None)
@click.option("--address", default=None)
@click.option("--agent-name", default=None)
def init(workdir: Optional[Path], no_interactive: bool, api_key: Optional[str],
         permission_mode: Optional[str], broker_url: Optional[str], agent_id: Optional[str],
         address: Optional[str], agent_name: Optional[str]) -> None:
    code = init_cmd.run(
        workdir=workdir,
        no_interactive=no_interactive,
        api_key=api_key,
        permission_mode=permission_mode,
        broker_url=broker_url,
        agent_id=agent_id,
        address=address,
        agent_name=agent_name,
    )
    sys.exit(code)


@cli.group("config", help="Inspect or edit .agent-mailer/config.toml.")
def config_group() -> None:
    pass


@config_group.command("show", help="Print config.toml (api_key masked).")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def config_show(workdir: Optional[Path]) -> None:
    sys.exit(config_cmd.show(workdir))


@config_group.command("set", help="Set a config value (e.g. permission_mode plan).")
@click.argument("key")
@click.argument("value")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def config_set(key: str, value: str, workdir: Optional[Path]) -> None:
    sys.exit(config_cmd.set_value(workdir, key, value))


@config_group.command("edit", help="Open config.toml in $EDITOR.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def config_edit(workdir: Optional[Path]) -> None:
    sys.exit(config_cmd.edit(workdir))


@cli.command("doctor", help="Health check: claude on PATH, perms, broker, config.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def doctor(workdir: Optional[Path]) -> None:
    sys.exit(doctor_cmd.run(workdir))


@cli.command("verify", help="Re-validate api_key with broker.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def verify(workdir: Optional[Path]) -> None:
    sys.exit(verify_cmd.run(workdir))


@cli.command("status", help="(M6) Show current watcher status.")
def status() -> None:
    click.echo("status: not implemented yet (planned for M6).", err=True)
    sys.exit(2)


@cli.command("logs", help="(M6) Tail the structured log.")
def logs() -> None:
    click.echo("logs: not implemented yet (planned for M6).", err=True)
    sys.exit(2)


@cli.group("sessions", help="(M3) Manage thread → claude session mappings.")
def sessions_group() -> None:
    pass


@sessions_group.command("list")
def sessions_list() -> None:
    click.echo("sessions list: not implemented yet (planned for M3).", err=True)
    sys.exit(2)


@sessions_group.command("show")
@click.argument("thread_id")
def sessions_show(thread_id: str) -> None:
    click.echo("sessions show: not implemented yet (planned for M3).", err=True)
    sys.exit(2)


@sessions_group.command("invalidate")
@click.argument("thread_id")
def sessions_invalidate(thread_id: str) -> None:
    click.echo("sessions invalidate: not implemented yet (planned for M3).", err=True)
    sys.exit(2)


@sessions_group.command("prune")
@click.option("--older-than", default="14d")
def sessions_prune(older_than: str) -> None:
    click.echo("sessions prune: not implemented yet (planned for M3).", err=True)
    sys.exit(2)


@cli.group("memory", help="(M4) Manage agent memory files.")
def memory_group() -> None:
    pass


@memory_group.command("show")
@click.option("--thread", default=None)
def memory_show(thread: Optional[str]) -> None:
    click.echo("memory show: not implemented yet (planned for M4).", err=True)
    sys.exit(2)


@memory_group.command("edit")
@click.option("--thread", default=None)
def memory_edit(thread: Optional[str]) -> None:
    click.echo("memory edit: not implemented yet (planned for M4).", err=True)
    sys.exit(2)


@memory_group.command("ls")
def memory_ls() -> None:
    click.echo("memory ls: not implemented yet (planned for M4).", err=True)
    sys.exit(2)


@cli.group("dead-letter", help="(M5) Manage messages that exhausted retries.")
def dead_letter_group() -> None:
    pass


@dead_letter_group.command("list")
def dead_letter_list() -> None:
    click.echo("dead-letter list: not implemented yet (planned for M5).", err=True)
    sys.exit(2)


@dead_letter_group.command("retry")
@click.argument("msg_id")
def dead_letter_retry(msg_id: str) -> None:
    click.echo("dead-letter retry: not implemented yet (planned for M5).", err=True)
    sys.exit(2)


@dead_letter_group.command("purge")
def dead_letter_purge() -> None:
    click.echo("dead-letter purge: not implemented yet (planned for M5).", err=True)
    sys.exit(2)


@cli.command("fetch", help="Fetch a single message from the broker (debug).")
@click.argument("msg_id")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def fetch(msg_id: str, workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import fetch_cmd
    sys.exit(fetch_cmd.run(workdir, msg_id))


@cli.command("test-claude", help="Run a minimal `claude -p` to verify integration.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def test_claude(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import test_claude_cmd
    sys.exit(test_claude_cmd.run(workdir))


if __name__ == "__main__":
    cli()
