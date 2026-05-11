"""Memory directory + global.md template management (SPEC §12).

The watcher creates `<workdir>/.agent-mailer/memory/` with mode 0700 and seeds
`global.md` with the §12.2 template on first start. Per-thread handoff notes
(`<thread_id>.md`) are NOT pre-created — Claude writes them when it builds
non-obvious judgments worth carrying across sessions.
"""
from __future__ import annotations

import os
from pathlib import Path


GLOBAL_TEMPLATE = """\
# Global Memory for {agent_name}

This file is your long-term memory across all threads.
Append entries when you build judgments that apply broadly.

## Working Style Preferences
(Add as you learn user preferences)

## Domain Knowledge
(Add as you build understanding of recurring concepts)

## Avoid Patterns
(Add anti-patterns you've encountered)
"""


def memory_dir(workdir: Path) -> Path:
    return workdir / ".agent-mailer" / "memory"


def global_md_path(workdir: Path) -> Path:
    return memory_dir(workdir) / "global.md"


def thread_md_path(workdir: Path, thread_id: str) -> Path:
    return memory_dir(workdir) / f"{thread_id}.md"


def ensure_memory_dir(workdir: Path) -> Path:
    """Create .agent-mailer/memory/ at 0700 if absent. Idempotent."""
    md = memory_dir(workdir)
    md.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Tighten in case it pre-existed with looser perms.
    os.chmod(md, 0o700)
    return md


def ensure_global_md(workdir: Path, *, agent_name: str) -> Path:
    """Create memory/global.md from §12.2 template if absent.

    Existing files are left alone — Claude / the human may have edited them.
    """
    ensure_memory_dir(workdir)
    path = global_md_path(workdir)
    if path.exists():
        return path
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(GLOBAL_TEMPLATE.format(agent_name=agent_name or "this agent"))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return path


def list_memory_files(workdir: Path) -> list[Path]:
    md = memory_dir(workdir)
    if not md.exists():
        return []
    return sorted(p for p in md.iterdir() if p.is_file() and p.suffix == ".md")
