"""Spawn the headless Claude Code subprocess and capture its output.

Wraps asyncio.create_subprocess_exec with a wait_for timeout (default 1800s,
§9 / §10). The watcher uses run_claude(); tests can substitute build_cmd.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 1800


@dataclass
class ClaudeResult:
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    parsed: Optional[dict] = None
    parse_error: Optional[str] = None


class ClaudeRunError(Exception):
    pass


class ClaudeNotFoundError(ClaudeRunError):
    pass


class ClaudeTimeoutError(ClaudeRunError):
    pass


def build_cmd(
    *,
    claude_command: str,
    prompt: str,
    permission_mode: str,
    session_id: Optional[str] = None,
) -> list[str]:
    cmd = [
        claude_command,
        "-p", prompt,
        "--output-format", "json",
        "--permission-mode", permission_mode,
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


async def run_claude(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ClaudeResult:
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).is_absolute():
        raise ClaudeNotFoundError(
            f"Claude CLI not found on PATH: {cmd[0]!r}. Install it (e.g. via "
            f"`npm install -g @anthropic-ai/claude-code`) or set claude_command "
            f"in config.toml."
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
        raise ClaudeNotFoundError(str(exc)) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        raise ClaudeTimeoutError(
            f"claude subprocess exceeded {timeout_seconds}s timeout"
        ) from exc

    duration = time.monotonic() - started_at
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    parsed: Optional[dict] = None
    parse_error: Optional[str] = None
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            parse_error = f"claude stdout was not valid JSON: {exc}"
    return ClaudeResult(
        return_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        parsed=parsed,
        parse_error=parse_error,
    )
