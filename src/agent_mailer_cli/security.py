"""Filesystem permission checks, .gitignore maintenance, and the watcher lock."""
from __future__ import annotations

import errno
import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

GITIGNORE_LINE = ".agent-mailer/"


class SecurityError(Exception):
    """Raised when filesystem permissions are too loose to run the watcher."""


def check_workdir_security(workdir: Path) -> None:
    """Enforce config dir <=0700 and config file <=0600 (§7.4 / §15.6).

    Missing files raise SecurityError too — callers (watch) require a configured
    workdir before this check runs.
    """
    cfg_dir = workdir / ".agent-mailer"
    cfg_file = cfg_dir / "config.toml"

    if not cfg_dir.exists():
        raise SecurityError(
            f"{cfg_dir} does not exist. Run `agent-mailer init` from this workdir."
        )
    if not cfg_file.exists():
        raise SecurityError(
            f"{cfg_file} does not exist. Run `agent-mailer init` to create it."
        )

    dir_mode = cfg_dir.stat().st_mode & 0o777
    if dir_mode & 0o077:
        raise SecurityError(
            f"{cfg_dir} has insecure permissions {oct(dir_mode)}; "
            f"run: chmod 700 {cfg_dir}"
        )

    file_mode = cfg_file.stat().st_mode & 0o777
    if file_mode & 0o077:
        raise SecurityError(
            f"{cfg_file} has insecure permissions {oct(file_mode)}; "
            f"run: chmod 600 {cfg_file}"
        )


def fix_permissions(workdir: Path) -> None:
    """Best-effort: tighten .agent-mailer/ and config.toml to 0700/0600."""
    cfg_dir = workdir / ".agent-mailer"
    cfg_file = cfg_dir / "config.toml"
    if cfg_dir.exists():
        os.chmod(cfg_dir, 0o700)
    if cfg_file.exists():
        os.chmod(cfg_file, 0o600)


def ensure_gitignore(workdir: Path) -> tuple[bool, Path]:
    """Append `.agent-mailer/` to <workdir>/.gitignore if missing.

    Returns (was_modified, gitignore_path). Creates the file if absent.
    """
    path = workdir / ".gitignore"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip() == GITIGNORE_LINE.strip():
                return False, path
            # Tolerate ".agent-mailer" without trailing slash too.
            if line.strip() == ".agent-mailer":
                return False, path
        if not text.endswith("\n"):
            text += "\n"
        text += GITIGNORE_LINE + "\n"
        path.write_text(text, encoding="utf-8")
        return True, path
    path.write_text(GITIGNORE_LINE + "\n", encoding="utf-8")
    return True, path


def gitignore_covers(workdir: Path) -> bool:
    path = workdir / ".gitignore"
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token in (".agent-mailer/", ".agent-mailer"):
            return True
    return False


@contextmanager
def watcher_lock(workdir: Path) -> Iterator[Path]:
    """Acquire an exclusive flock on .agent-mailer/.lock (§15.1).

    Yields the lock path. Raises SecurityError if another watcher holds it.
    """
    cfg_dir = workdir / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700, exist_ok=True)
    lock_path = cfg_dir / ".lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise SecurityError(
                    f"Another watcher is already running for {workdir} "
                    f"(holding {lock_path}). Stop it before starting another."
                ) from exc
            raise
        os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
        yield lock_path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def is_world_or_group_readable(path: Path) -> bool:
    if not path.exists():
        return False
    return bool(path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
