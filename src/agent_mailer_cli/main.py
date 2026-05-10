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
from agent_mailer_cli.config import VALID_RUNTIMES
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


@cli.command("watch", help="Poll the broker inbox and spawn the configured runtime per message.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Workdir to operate on (default: current directory).")
@click.option("--broker-url", default=None, help="Override broker_url from config.toml.")
@click.option("--api-key", default=None, help="Override api_key from config.toml.")
@click.option("--agent-id", default=None, help="Override agent_id from config.toml.")
@click.option("--address", default=None, help="Override address from config.toml.")
@click.option("--permission-mode", type=click.Choice(["acceptEdits", "bypassPermissions", "plan"]),
              default=None, help="Override permission_mode from config.toml.")
@click.option("--runtime", type=click.Choice(VALID_RUNTIMES), default=None,
              help="Override runtime from config.toml.")
@click.option("--claude-command", default=None, help="Override claude_command from config.toml.")
@click.option("--codex-command", default=None, help="Override codex_command from config.toml.")
@click.option("--poll-interval-idle", type=int, default=None, help="Override idle poll interval (s).")
@click.option("--poll-interval-active", type=int, default=None, help="Override active poll interval (s).")
@click.option("--max-retries", type=int, default=None, help="Override max_retries.")
@click.option("--no-interactive", is_flag=True, default=False,
              help="Refuse to prompt; missing fields cause exit 2.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Poll only; do not spawn the local runtime. Useful for debugging connectivity.")
@click.option("--ignore-agent-md-mismatch", is_flag=True, default=False,
              help="Skip the SPEC §15.6 #5 check that AGENT.md and config.toml "
                   "agree on agent_id. Use only for fixtures/tests.")
def watch(workdir: Optional[Path], broker_url: Optional[str], api_key: Optional[str],
          agent_id: Optional[str], address: Optional[str], permission_mode: Optional[str],
          runtime: Optional[str], claude_command: Optional[str], codex_command: Optional[str],
          poll_interval_idle: Optional[int], poll_interval_active: Optional[int],
          max_retries: Optional[int], no_interactive: bool, dry_run: bool,
          ignore_agent_md_mismatch: bool) -> None:
    code = watch_cmd.run(
        workdir=workdir,
        broker_url=broker_url,
        api_key=api_key,
        agent_id=agent_id,
        address=address,
        permission_mode=permission_mode,
        runtime=runtime,
        claude_command=claude_command,
        codex_command=codex_command,
        poll_interval_idle=poll_interval_idle,
        poll_interval_active=poll_interval_active,
        max_retries=max_retries,
        no_interactive=no_interactive,
        dry_run=dry_run,
        ignore_agent_md_mismatch=ignore_agent_md_mismatch,
    )
    sys.exit(code)


@cli.command("init", help="Run the wizard but do not enter the watch loop.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--no-interactive", is_flag=True, default=False)
@click.option("--api-key", default=None)
@click.option("--permission-mode", type=click.Choice(["acceptEdits", "bypassPermissions", "plan"]),
              default=None)
@click.option("--runtime", type=click.Choice(VALID_RUNTIMES), default=None)
@click.option("--claude-command", default=None)
@click.option("--codex-command", default=None)
@click.option("--broker-url", default=None)
@click.option("--agent-id", default=None)
@click.option("--address", default=None)
@click.option("--agent-name", default=None)
def init(workdir: Optional[Path], no_interactive: bool, api_key: Optional[str],
         permission_mode: Optional[str], runtime: Optional[str],
         claude_command: Optional[str], codex_command: Optional[str],
         broker_url: Optional[str], agent_id: Optional[str],
         address: Optional[str], agent_name: Optional[str]) -> None:
    code = init_cmd.run(
        workdir=workdir,
        no_interactive=no_interactive,
        api_key=api_key,
        permission_mode=permission_mode,
        runtime=runtime,
        claude_command=claude_command,
        codex_command=codex_command,
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


@cli.command("status", help="Show current watcher status (PID, inflight, dead-letter, last log event).")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def status(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import status_cmd
    sys.exit(status_cmd.run(workdir))


@cli.command("logs", help="Tail the structured log.jsonl with optional --grep filter.")
@click.option("--tail", "tail_n", type=int, default=20, help="Number of trailing lines (default 20).")
@click.option("--grep", "pattern", default=None,
              help="Substring filter (matches the JSON line text).")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def logs(tail_n: int, pattern: Optional[str], workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import logs_cmd
    sys.exit(logs_cmd.run(workdir, tail_n=tail_n, pattern=pattern))


@cli.group("sessions", help="Manage thread → runtime session mappings.")
def sessions_group() -> None:
    pass


@sessions_group.command("list")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def sessions_list(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import sessions_cmd
    sys.exit(sessions_cmd.list_sessions(workdir))


@sessions_group.command("show")
@click.argument("thread_id")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def sessions_show(thread_id: str, workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import sessions_cmd
    sys.exit(sessions_cmd.show_session(workdir, thread_id))


@sessions_group.command("invalidate")
@click.argument("thread_id")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def sessions_invalidate(thread_id: str, workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import sessions_cmd
    sys.exit(sessions_cmd.invalidate_session(workdir, thread_id))


@sessions_group.command("prune")
@click.option("--older-than", default="14d")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def sessions_prune(older_than: str, workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import sessions_cmd
    sys.exit(sessions_cmd.prune_sessions(workdir, older_than))


@cli.group("memory", help="Manage agent memory files (global + per-thread handoff notes).")
def memory_group() -> None:
    pass


@memory_group.command("show")
@click.option("--thread", default=None, help="Show <thread_id>.md instead of global.md.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def memory_show(thread: Optional[str], workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import memory_cmd
    sys.exit(memory_cmd.show(workdir, thread))


@memory_group.command("edit")
@click.option("--thread", default=None, help="Edit <thread_id>.md instead of global.md.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def memory_edit(thread: Optional[str], workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import memory_cmd
    sys.exit(memory_cmd.edit(workdir, thread))


@memory_group.command("ls")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def memory_ls(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import memory_cmd
    sys.exit(memory_cmd.ls(workdir))


@cli.group("dead-letter", help="Manage messages that exhausted retry budget.")
def dead_letter_group() -> None:
    pass


@dead_letter_group.command("list")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def dead_letter_list(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import dead_letter_cmd
    sys.exit(dead_letter_cmd.list_dead_letter(workdir))


@dead_letter_group.command("retry")
@click.argument("msg_id")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def dead_letter_retry(msg_id: str, workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import dead_letter_cmd
    sys.exit(dead_letter_cmd.retry_dead_letter(workdir, msg_id))


@dead_letter_group.command("purge")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
def dead_letter_purge(workdir: Optional[Path]) -> None:
    from agent_mailer_cli.commands import dead_letter_cmd
    sys.exit(dead_letter_cmd.purge_dead_letter(workdir))


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
