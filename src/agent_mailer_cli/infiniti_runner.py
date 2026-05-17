"""Spawn the LinkYun Infiniti Agent CLI non-interactively.

Infiniti differs from claude/codex in two ways that shape this module:

1. Session is project-scoped, not turn-scoped. Infiniti persists conversation
   state in `.infiniti-agent/` inside the cwd, so resume is implicit — there is
   no `--resume <id>` flag and no session_id in stdout. SessionStore therefore
   never records anything for an infiniti runtime; `is_resume` is effectively
   always False from the runner's perspective, but infiniti picks up where it
   left off automatically.

2. Permission mode is not surfaced by the CLI. claude/codex accept
   acceptEdits/bypassPermissions/plan equivalents; infiniti has no such flag.
   The watcher still records permission_mode in config.toml for audit, but
   this runner ignores it.

Invocation surface (confirmed via `infiniti-agent cli --help`):
    infiniti-agent cli <prompt...>     # 非交互执行一轮

Exit code 0 = success; non-zero = failure (treated like claude/codex by the
watcher's retry/dead-letter loop).
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Optional

from agent_mailer_cli.claude_runner import (
    DEFAULT_TIMEOUT_SECONDS,
    ClaudeResult,
)


class InfinitiRunError(Exception):
    pass


class InfinitiNotFoundError(InfinitiRunError):
    pass


class InfinitiTimeoutError(InfinitiRunError):
    pass


def build_cmd(
    *,
    infiniti_command: str,
    prompt: str,
    permission_mode: str = "",  # noqa: ARG001 — accepted for symmetry; infiniti ignores it
    project_dir: str | None = None,  # noqa: ARG001 — infiniti operates on cwd
    session_id: Optional[str] = None,  # noqa: ARG001 — infiniti manages sessions internally
) -> list[str]:
    return [infiniti_command, "cli", prompt]


async def run_infiniti(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ClaudeResult:
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).is_absolute():
        raise InfinitiNotFoundError(
            f"Infiniti CLI not found on PATH: {cmd[0]!r}. Install it (npm i -g "
            f"infiniti-agent) or set infiniti_command in config.toml."
        )

    started_at = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise InfinitiNotFoundError(str(exc)) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        raise InfinitiTimeoutError(
            f"infiniti subprocess exceeded {timeout_seconds}s timeout"
        ) from exc

    duration = time.monotonic() - started_at
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    # No JSON/JSONL contract on infiniti's stdout — leave parsed=None so the
    # watcher records process_done without a session_id (correct: SessionStore
    # has nothing to resume against; infiniti's own .infiniti-agent/ does).
    return ClaudeResult(
        return_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        parsed=None,
        parse_error=None,
    )
