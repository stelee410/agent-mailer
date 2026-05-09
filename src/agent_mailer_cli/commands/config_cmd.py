"""Implementation of `agent-mailer config show|set|edit`."""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import fields
from pathlib import Path
from typing import Optional

import click

from agent_mailer_cli.config import (
    Config,
    ConfigError,
    config_file_path,
    load_config,
    mask_api_key,
    update_field,
)


def show(workdir: Optional[Path]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        cfg = load_config(workdir_path)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    if cfg is None:
        click.echo(f"❌ No config.toml at {config_file_path(workdir_path)}", err=True)
        return 2
    cfg.workdir = workdir_path

    click.echo(f"# {cfg.cfg_file}")
    for f in fields(cfg):
        if f.name == "workdir":
            continue
        value = getattr(cfg, f.name)
        if f.name == "api_key":
            click.echo(f"{f.name} = {mask_api_key(value)!r}")
        else:
            click.echo(f"{f.name} = {value!r}")
    return 0


def set_value(workdir: Optional[Path], key: str, value: str) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    try:
        update_field(workdir_path, key, value)
    except ConfigError as exc:
        click.echo(f"❌ {exc}", err=True)
        return 2
    click.echo(f"✓ Set {key} = {value!r}")
    return 0


def edit(workdir: Optional[Path]) -> int:
    workdir_path = (workdir or Path.cwd()).resolve()
    path = config_file_path(workdir_path)
    if not path.exists():
        click.echo(f"❌ No config.toml at {path}", err=True)
        return 2
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    cmd = shlex.split(editor) + [str(path)]
    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        click.echo(f"❌ Editor not found: {editor!r}", err=True)
        return 2
    return result.returncode
