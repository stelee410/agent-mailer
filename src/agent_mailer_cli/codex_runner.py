"""Spawn the Codex CLI non-interactively and capture its output."""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from agent_mailer_cli.claude_runner import (
    DEFAULT_TIMEOUT_SECONDS,
    ClaudeResult,
)


class CodexRunError(Exception):
    pass


class CodexNotFoundError(CodexRunError):
    pass


class CodexTimeoutError(CodexRunError):
    pass


def build_cmd(
    *,
    codex_command: str,
    prompt: str,
    permission_mode: str,
    session_id: Optional[str] = None,
) -> list[str]:
    cmd = [codex_command, *_permission_args(permission_mode), "exec"]
    if session_id:
        cmd += ["resume", "--json", "--skip-git-repo-check", session_id, prompt]
    else:
        cmd += ["--json", "--skip-git-repo-check", prompt]
    return cmd


async def run_codex(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ClaudeResult:
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).is_absolute():
        raise CodexNotFoundError(
            f"Codex CLI not found on PATH: {cmd[0]!r}. Install it or set "
            f"codex_command in config.toml."
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
        raise CodexNotFoundError(str(exc)) from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        raise CodexTimeoutError(
            f"codex subprocess exceeded {timeout_seconds}s timeout"
        ) from exc

    duration = time.monotonic() - started_at
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    parsed, parse_error = parse_codex_output(stdout)
    return ClaudeResult(
        return_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        parsed=parsed,
        parse_error=parse_error,
    )


def parse_codex_output(stdout: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    text = stdout.strip()
    if not text:
        return None, None

    events: list[Any] = []
    parse_errors: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            parse_errors.append(str(exc))

    if not events:
        return None, f"codex stdout was not valid JSONL: {'; '.join(parse_errors[:3])}"

    session_id = None
    for event in events:
        session_id = _find_first_key(event, {"session_id", "conversation_id"}) or session_id

    out: dict[str, Any] = {"events": len(events)}
    if session_id:
        out["session_id"] = session_id
    if parse_errors:
        out["jsonl_parse_warnings"] = parse_errors[:3]
    return out, None


def _permission_args(permission_mode: str) -> list[str]:
    if permission_mode == "bypassPermissions":
        return ["--dangerously-bypass-approvals-and-sandbox"]
    if permission_mode == "plan":
        return ["--sandbox", "read-only", "--ask-for-approval", "never"]
    return ["--sandbox", "workspace-write", "--ask-for-approval", "never"]


def _find_first_key(value: Any, keys: set[str]) -> Optional[str]:
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        for item in value.values():
            found = _find_first_key(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_key(item, keys)
            if found:
                return found
    return None
