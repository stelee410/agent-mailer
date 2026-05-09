"""Async watch loop: poll inbox, spawn claude, manage local state."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.broker import (
    BrokerClient,
    InboxMessage,
    PermanentBrokerError,
    TransientBrokerError,
    backoff_delay,
    sleep_with_jitter,
)
from agent_mailer_cli.claude_runner import (
    ClaudeNotFoundError,
    ClaudeResult,
    ClaudeRunError,
    ClaudeTimeoutError,
    build_cmd,
    run_claude,
)
from agent_mailer_cli.config import Config
from agent_mailer_cli.prompt import build_prompt
from agent_mailer_cli.state import LocalState

log = logging.getLogger("agent_mailer_cli.watch")


class WatchAborted(Exception):
    """Raised to bail out of the loop with a non-retryable error."""


async def watch_loop(cfg: Config, *, dry_run: bool = False) -> int:
    """Run the watch loop until cancelled or a permanent error occurs.

    Returns a process exit code.
    """
    if cfg.workdir is None:
        raise WatchAborted("internal error: cfg.workdir not set")

    state = LocalState(cfg.cfg_dir)
    state.append_log("watch_started", agent=cfg.agent_name, address=cfg.address,
                     dry_run=dry_run)

    inflight = state.load_inflight()
    if inflight is not None:
        # M2: best-effort recovery — log + clear. M5 will add retry/dead-letter.
        state.append_log("inflight_found_at_startup", msg_id=inflight.msg_id,
                         started_at=inflight.started_at, retry_count=inflight.retry_count)
        click.echo(
            f"[!] Found stale inflight record for {inflight.msg_id} "
            f"(started {inflight.started_at}). Clearing — message will be retried "
            f"on next poll if still unread."
        )
        state.clear_inflight()

    async with BrokerClient(cfg.broker_url, cfg.api_key) as client:
        try:
            verify_data = await client.verify_agent(cfg.agent_id)
        except PermanentBrokerError as exc:
            click.echo(f"❌ Broker rejected credentials: {exc}", err=True)
            state.append_log("verify_failed", status=exc.status_code, error=str(exc))
            return 2
        except TransientBrokerError as exc:
            click.echo(f"❌ Broker not reachable: {exc}", err=True)
            state.append_log("verify_unreachable", error=str(exc))
            return 3

        broker_address = verify_data.get("address", cfg.address)
        if broker_address and broker_address != cfg.address:
            click.echo(
                f"⚠️  Broker reports address {broker_address!r} but config has "
                f"{cfg.address!r}. Trusting config."
            )
        click.echo(f"✓ Verified {cfg.agent_name} ({cfg.address}) at {cfg.broker_url}")
        click.echo(
            f"⏳ Polling every {cfg.poll_interval_idle}s idle / "
            f"{cfg.poll_interval_active}s active..."
        )
        if dry_run:
            click.echo("ℹ️  Dry run: claude will NOT be spawned.")

        consecutive_errors = 0
        while True:
            try:
                msgs = await client.fetch_inbox(cfg.address, cfg.agent_id)
            except PermanentBrokerError as exc:
                click.echo(f"❌ Broker permanent error: {exc}", err=True)
                state.append_log("poll_permanent_error", status=exc.status_code,
                                 error=str(exc))
                return 2
            except TransientBrokerError as exc:
                consecutive_errors += 1
                delay = backoff_delay(consecutive_errors)
                state.append_log("poll_transient_error", attempt=consecutive_errors,
                                 sleep=delay, error=str(exc))
                click.echo(f"⚠️  Broker transient error (attempt {consecutive_errors}): "
                           f"{exc}. Backing off {delay:.0f}s.")
                await asyncio.sleep(delay)
                continue
            consecutive_errors = 0

            unread = [m for m in msgs if not m.is_read]
            new_msgs = [m for m in unread if m.id not in state.processed]
            state.append_log("poll_inbox", total=len(msgs), unread=len(unread),
                             new=len(new_msgs))

            for msg in new_msgs:
                await _handle_message(msg, cfg, state, dry_run=dry_run)

            interval = cfg.poll_interval_active if new_msgs else cfg.poll_interval_idle
            await sleep_with_jitter(interval)


async def _handle_message(msg: InboxMessage, cfg: Config, state: LocalState,
                          *, dry_run: bool) -> None:
    state.set_inflight(msg.id, msg.thread_id)
    state.append_log("process_start", msg_id=msg.id, thread_id=msg.thread_id,
                     subject=msg.subject, from_agent=msg.from_agent, dry_run=dry_run)
    click.echo(f"→ New message {msg.id} in thread {msg.thread_id} "
               f"from {msg.from_agent}: {msg.subject!r}")

    if dry_run:
        # Treat as processed so we don't loop on it next poll.
        state.add_processed(msg.id)
        state.save_cursor(msg.id)
        state.clear_inflight()
        state.append_log("process_dry_run", msg_id=msg.id)
        click.echo(f"  (dry-run) marked {msg.id} as processed locally; "
                   f"no claude spawned.")
        return

    prompt = build_prompt(msg, broker_url=cfg.broker_url, is_resume=False)
    cmd = build_cmd(
        claude_command=cfg.claude_command,
        prompt=prompt,
        permission_mode=cfg.permission_mode or "acceptEdits",
    )

    try:
        result: ClaudeResult = await run_claude(cmd, cwd=cfg.workdir or Path.cwd())
    except ClaudeNotFoundError as exc:
        click.echo(f"❌ {exc}", err=True)
        state.append_log("claude_not_found", msg_id=msg.id, error=str(exc))
        state.clear_inflight()
        # Bail entirely — claude missing is a config issue, not a per-message one.
        raise WatchAborted(str(exc)) from exc
    except ClaudeTimeoutError as exc:
        click.echo(f"⚠️  claude timed out for {msg.id}: {exc}")
        state.append_log("claude_timeout", msg_id=msg.id, error=str(exc))
        state.clear_inflight()
        return
    except ClaudeRunError as exc:
        click.echo(f"⚠️  claude run error for {msg.id}: {exc}")
        state.append_log("claude_run_error", msg_id=msg.id, error=str(exc))
        state.clear_inflight()
        return

    if result.return_code != 0:
        click.echo(f"⚠️  claude exited {result.return_code} for {msg.id} — "
                   f"will retry on next poll.")
        state.append_log("claude_failed", msg_id=msg.id,
                         return_code=result.return_code,
                         duration_ms=int(result.duration_seconds * 1000),
                         stderr_tail=result.stderr[-400:])
        state.clear_inflight()
        return

    session_id: Optional[str] = None
    cost: Optional[float] = None
    if result.parsed:
        session_id = result.parsed.get("session_id")
        cost = result.parsed.get("total_cost_usd")
    elif result.parse_error:
        state.append_log("claude_output_unparsed", msg_id=msg.id,
                         parse_error=result.parse_error,
                         stdout_tail=result.stdout[-400:])

    state.add_processed(msg.id)
    state.save_cursor(msg.id)
    state.clear_inflight()

    extras: dict[str, object] = {
        "duration_ms": int(result.duration_seconds * 1000),
    }
    if session_id:
        extras["session_id"] = session_id
    if cost is not None:
        extras["cost_usd"] = cost
    state.append_log("process_done", msg_id=msg.id, **extras)

    cost_str = f" (${cost:.2f})" if cost is not None else ""
    click.echo(f"✓ Processed {msg.id} in {result.duration_seconds:.1f}s{cost_str}")
