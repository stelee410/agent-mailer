"""config.toml read / write / validation.

The schema is small enough that we hand-write the TOML output rather than
pulling in tomli_w. Reads use stdlib tomllib (Python 3.11+).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Optional

VALID_PERMISSION_MODES = ("acceptEdits", "bypassPermissions", "plan")
VALID_RUNTIMES = ("claude", "codex")

# Required for runtime; permission_mode is checked separately because the
# decision tree in §8.1 routes "missing permission_mode" to a single-question
# wizard, not to a hard error.
RUNTIME_REQUIRED_FIELDS = ("agent_id", "agent_name", "address", "broker_url", "api_key")


class ConfigError(Exception):
    """Raised on malformed or insecure config.toml."""


@dataclass
class Config:
    agent_id: str = ""
    agent_name: str = ""
    address: str = ""
    broker_url: str = ""
    api_key: str = ""
    permission_mode: str = ""
    poll_interval_idle: int = 60
    poll_interval_active: int = 10
    max_retries: int = 3
    session_max_age_days: int = 7
    session_max_turns: int = 50
    runtime: str = "claude"
    claude_command: str = "claude"
    codex_command: str = "codex"
    project_dir: str = ""

    # Convenience: not persisted, set by callers.
    workdir: Optional[Path] = field(default=None, repr=False, compare=False)

    @property
    def cfg_dir(self) -> Path:
        if self.workdir is None:
            raise ConfigError("Config.workdir is not set")
        return self.workdir / ".agent-mailer"

    @property
    def cfg_file(self) -> Path:
        return self.cfg_dir / "config.toml"

    def missing_runtime_fields(self) -> list[str]:
        return [name for name in RUNTIME_REQUIRED_FIELDS if not getattr(self, name)]

    def merge_overrides(self, **overrides: object) -> "Config":
        clean = {k: v for k, v in overrides.items() if v is not None and v != ""}
        return replace(self, **clean)

    def to_toml(self) -> str:
        return _render_toml(self)


def config_file_path(workdir: Path) -> Path:
    return workdir / ".agent-mailer" / "config.toml"


def load_config(workdir: Path) -> Optional[Config]:
    """Load config.toml. Returns None if file does not exist."""
    path = config_file_path(workdir)
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    cfg = Config(workdir=workdir)
    int_fields = {
        "poll_interval_idle", "poll_interval_active", "max_retries",
        "session_max_age_days", "session_max_turns",
    }
    str_fields = {
        "agent_id", "agent_name", "address", "broker_url", "api_key",
        "permission_mode", "runtime", "claude_command", "codex_command", "project_dir",
    }
    for key, value in data.items():
        if key in str_fields:
            if not isinstance(value, str):
                raise ConfigError(f"{path}: '{key}' must be a string")
            setattr(cfg, key, value)
        elif key in int_fields:
            if not isinstance(value, int):
                raise ConfigError(f"{path}: '{key}' must be an integer")
            setattr(cfg, key, value)
        else:
            # Unknown keys are tolerated but ignored — keeps forward compatibility.
            pass

    if cfg.permission_mode and cfg.permission_mode not in VALID_PERMISSION_MODES:
        raise ConfigError(
            f"{path}: permission_mode must be one of {VALID_PERMISSION_MODES}, "
            f"got {cfg.permission_mode!r}"
        )
    if cfg.runtime not in VALID_RUNTIMES:
        raise ConfigError(
            f"{path}: runtime must be one of {VALID_RUNTIMES}, got {cfg.runtime!r}"
        )
    return cfg


def save_config(cfg: Config) -> Path:
    """Write config.toml with mode 0600 and ensure parent dir is 0700."""
    cfg_dir = cfg.cfg_dir
    cfg_dir.mkdir(mode=0o700, exist_ok=True)
    # exist_ok=True will not change permissions on an existing dir, so coerce.
    os.chmod(cfg_dir, 0o700)
    path = cfg.cfg_file
    body = cfg.to_toml()
    # Open with mode 0600 from the start to avoid a window where the file is
    # group/other-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return path


def update_field(workdir: Path, key: str, value: str) -> Config:
    """Update a single field in config.toml.

    Coerces the value to the field's expected type and validates
    permission_mode.
    """
    cfg = load_config(workdir)
    if cfg is None:
        raise ConfigError(
            f"No config.toml in {workdir / '.agent-mailer'}; run `agent-mailer init` first."
        )

    valid = {f.name for f in fields(cfg) if f.name != "workdir"}
    if key not in valid:
        raise ConfigError(f"Unknown config key: {key!r}. Valid keys: {sorted(valid)}")

    current = getattr(cfg, key)
    if isinstance(current, int) and not isinstance(current, bool):
        try:
            new_value: object = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} expects an integer, got {value!r}") from exc
    else:
        new_value = value

    if key == "permission_mode" and new_value not in VALID_PERMISSION_MODES:
        raise ConfigError(
            f"permission_mode must be one of {VALID_PERMISSION_MODES}, got {new_value!r}"
        )
    if key == "runtime" and new_value not in VALID_RUNTIMES:
        raise ConfigError(
            f"runtime must be one of {VALID_RUNTIMES}, got {new_value!r}"
        )

    setattr(cfg, key, new_value)
    save_config(cfg)
    return cfg


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:6]}…{api_key[-4:]}"


def _render_toml(cfg: Config) -> str:
    """Render the config dataclass to a stable TOML string.

    Field order matches §6.2 of the SPEC. We write strings and integers only;
    the schema has no booleans or arrays today.
    """
    lines = [
        "# Agent Mailer CLI runtime configuration.",
        "# Generated by `agent-mailer init` / `agent-mailer config`.",
        "# Permissions must remain 0600; the directory must remain 0700.",
        "",
        "# Agent identity (must match AGENT.md).",
        f'agent_id    = "{_escape(cfg.agent_id)}"',
        f'agent_name  = "{_escape(cfg.agent_name)}"',
        f'address     = "{_escape(cfg.address)}"',
        f'broker_url  = "{_escape(cfg.broker_url)}"',
        "",
        "# Credentials.",
        f'api_key     = "{_escape(cfg.api_key)}"',
        "",
        "# Watcher behavior.",
        f'permission_mode = "{_escape(cfg.permission_mode)}"',
        f"poll_interval_idle = {cfg.poll_interval_idle}",
        f"poll_interval_active = {cfg.poll_interval_active}",
        f"max_retries = {cfg.max_retries}",
        f"session_max_age_days = {cfg.session_max_age_days}",
        f"session_max_turns = {cfg.session_max_turns}",
        f'runtime = "{_escape(cfg.runtime)}"',
    ]
    if cfg.claude_command and cfg.claude_command != "claude":
        lines.append(f'claude_command = "{_escape(cfg.claude_command)}"')
    if cfg.codex_command and cfg.codex_command != "codex":
        lines.append(f'codex_command = "{_escape(cfg.codex_command)}"')
    if cfg.project_dir:
        lines.extend([
            "",
            "# Original project directory that launched this team.",
            f'project_dir = "{_escape(cfg.project_dir)}"',
        ])
    lines.append("")
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
