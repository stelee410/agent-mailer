"""Unit tests for agent_mailer_cli.config (load / save / update / mask)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent_mailer_cli.config import (
    Config,
    ConfigError,
    config_file_path,
    load_config,
    mask_api_key,
    save_config,
    update_field,
)


def _bare_config(workdir: Path) -> Config:
    return Config(
        workdir=workdir,
        agent_id="aaaa-bbbb-cccc",
        agent_name="coder",
        address="coder@admin.example.com",
        broker_url="https://broker.example.com",
        api_key="sk-amp-1234567890abcdef",
        permission_mode="acceptEdits",
    )


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    cfg = _bare_config(tmp_path)
    path = save_config(cfg)
    assert path == config_file_path(tmp_path)

    # Permissions: 0600 file, 0700 directory.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    loaded = load_config(tmp_path)
    assert loaded is not None
    assert loaded.agent_id == cfg.agent_id
    assert loaded.address == cfg.address
    assert loaded.api_key == cfg.api_key
    assert loaded.permission_mode == "acceptEdits"
    assert loaded.runtime == "claude"
    # Defaults survive the round trip.
    assert loaded.poll_interval_idle == 60
    assert loaded.poll_interval_active == 10


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_config(tmp_path) is None


def test_load_rejects_invalid_permission_mode(tmp_path: Path) -> None:
    cfg = _bare_config(tmp_path)
    cfg.permission_mode = "garbage"
    save_config(cfg)
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_rejects_invalid_runtime(tmp_path: Path) -> None:
    cfg = _bare_config(tmp_path)
    cfg.runtime = "not-a-runtime"
    save_config(cfg)
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_rejects_wrong_type(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700)
    (cfg_dir / "config.toml").write_text(
        'agent_id = "x"\nagent_name = "y"\naddress = "z"\nbroker_url = "u"\n'
        'api_key = "k"\npermission_mode = "acceptEdits"\n'
        'poll_interval_idle = "not-an-int"\n'
    )
    os.chmod(cfg_dir / "config.toml", 0o600)
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert "poll_interval_idle" in str(exc.value)


def test_update_field_validates_permission_mode(tmp_path: Path) -> None:
    save_config(_bare_config(tmp_path))
    with pytest.raises(ConfigError):
        update_field(tmp_path, "permission_mode", "garbage")
    update_field(tmp_path, "permission_mode", "plan")
    assert load_config(tmp_path).permission_mode == "plan"  # type: ignore[union-attr]
    update_field(tmp_path, "runtime", "codex")
    assert load_config(tmp_path).runtime == "codex"  # type: ignore[union-attr]


def test_update_field_int_coercion(tmp_path: Path) -> None:
    save_config(_bare_config(tmp_path))
    update_field(tmp_path, "poll_interval_idle", "30")
    assert load_config(tmp_path).poll_interval_idle == 30  # type: ignore[union-attr]
    with pytest.raises(ConfigError):
        update_field(tmp_path, "poll_interval_idle", "thirty")


def test_update_field_unknown_key_rejected(tmp_path: Path) -> None:
    save_config(_bare_config(tmp_path))
    with pytest.raises(ConfigError):
        update_field(tmp_path, "made_up_key", "x")


def test_missing_runtime_fields(tmp_path: Path) -> None:
    cfg = Config(workdir=tmp_path, agent_id="x", api_key="y")
    missing = cfg.missing_runtime_fields()
    assert "agent_name" in missing
    assert "address" in missing
    assert "broker_url" in missing
    assert "agent_id" not in missing
    assert "api_key" not in missing


def test_mask_api_key() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "*****"
    assert mask_api_key("sk-amp-abcd1234efgh") == "sk-amp…efgh"


def test_save_overwrites_with_strict_perms_even_if_existing_was_lax(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".agent-mailer"
    cfg_dir.mkdir(mode=0o755)
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text("# placeholder\n")
    os.chmod(cfg_path, 0o644)

    save_config(_bare_config(tmp_path))
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(cfg_dir.stat().st_mode) == 0o700
