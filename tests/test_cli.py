import os
import tempfile

os.environ.setdefault(
    "AGENT_MAILER_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-bytes-long",
)

import asyncio
import json
import shutil
import sys
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import agent_mailer.cli as cli_module
from agent_mailer.auth import hash_password, verify_password
from agent_mailer.bootstrap import ensure_bootstrap_invite_code
from agent_mailer.cli import (
    _bootstrap_admin,
    _cloud_init,
    _generate_invite_code,
    _login,
    _logout,
    _migrate_db,
    _normalize_team_name,
    _render_default_team_yaml,
    _up_team,
    _validate_team_spec,
    load_session,
    resolve_broker_url,
)
from agent_mailer.db import get_db, init_db
from agent_mailer.main import app


class Args:
    """Simple namespace to mimic argparse output."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
async def tmp_db(tmp_path):
    """Create a temp DB file, init schema, return path string."""
    db_file = str(tmp_path / "test.db")
    db = await get_db(db_file)
    await init_db(db)
    await db.close()
    return db_file


# --- bootstrap-admin ---


async def test_bootstrap_admin_success(tmp_db):
    args = Args(db=tmp_db, username="myadmin", password="password12345678")
    await _bootstrap_admin(args)

    db = await get_db(tmp_db)
    cursor = await db.execute("SELECT * FROM users WHERE username = 'myadmin'")
    user = await cursor.fetchone()
    assert user is not None
    assert user["is_superadmin"] == 1
    assert verify_password("password12345678", user["password_hash"])
    await db.close()


async def test_bootstrap_admin_fails_when_users_exist(tmp_db):
    # Create first admin
    args = Args(db=tmp_db, username="admin1", password="password12345678")
    await _bootstrap_admin(args)

    # Try to create second — should exit
    args2 = Args(db=tmp_db, username="admin2", password="password12345678")
    with pytest.raises(SystemExit) as exc_info:
        await _bootstrap_admin(args2)
    assert exc_info.value.code == 1


# --- generate-invite-code ---


async def test_generate_invite_code_success(tmp_db, capsys):
    # Create superadmin first
    args_ba = Args(db=tmp_db, username="admin", password="adminpass1234")
    await _bootstrap_admin(args_ba)

    args = Args(db=tmp_db, username="admin", password="adminpass1234")
    await _generate_invite_code(args)

    captured = capsys.readouterr()
    assert "Invite code:" in captured.out
    # Find the line with the invite code
    for line in captured.out.strip().split("\n"):
        if line.startswith("Invite code:"):
            code = line.split(": ", 1)[1].strip()
            break
    assert len(code) == 8

    # Verify code exists in DB
    db = await get_db(tmp_db)
    cursor = await db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["used_by"] is None
    await db.close()


async def test_generate_invite_code_wrong_password(tmp_db):
    args_ba = Args(db=tmp_db, username="admin", password="adminpass1234")
    await _bootstrap_admin(args_ba)

    args = Args(db=tmp_db, username="admin", password="wrongpass")
    with pytest.raises(SystemExit) as exc_info:
        await _generate_invite_code(args)
    assert exc_info.value.code == 1


async def test_generate_invite_code_non_superadmin(tmp_db):
    # Create superadmin
    args_ba = Args(db=tmp_db, username="admin", password="adminpass1234")
    await _bootstrap_admin(args_ba)

    # Create regular user directly in DB
    db = await get_db(tmp_db)
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "regular", hash_password("regularpass12"), 0, now),
    )
    await db.commit()
    await db.close()

    args = Args(db=tmp_db, username="regular", password="regularpass12")
    with pytest.raises(SystemExit) as exc_info:
        await _generate_invite_code(args)
    assert exc_info.value.code == 1


# --- migrate-db ---


async def test_migrate_db(tmp_db, capsys):
    # Set up legacy data: agents with @local addresses, no user_id
    db = await get_db(tmp_db)
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Create legacy agents (no user_id)
    agent1_id = str(uuid.uuid4())
    agent2_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (agent1_id, "coder", "coder@local", "coder", "A coder", now),
    )
    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (agent2_id, "planner", "planner@local", "planner", "A planner", now),
    )

    # Create a message between them
    msg_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, thread_id, "planner@local", "coder@local", "send", "Task", "Do this", now),
    )

    # Create human operator (legacy)
    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("00000000-0000-0000-0000-000000000000", "Human Operator", "human-operator@local", "operator", "", now),
    )
    await db.commit()
    await db.close()

    # Run migration
    args = Args(db=tmp_db, password="migrate-pass-123")
    await _migrate_db(args)

    captured = capsys.readouterr()
    assert "Migration complete" in captured.out
    assert "Backup created" in captured.out

    # Verify
    db = await get_db(tmp_db)

    # Admin user created
    cursor = await db.execute("SELECT * FROM users WHERE username = 'admin'")
    admin = await cursor.fetchone()
    assert admin is not None
    assert admin["is_superadmin"] == 1

    # All agents have user_id
    cursor = await db.execute("SELECT * FROM agents WHERE user_id IS NULL")
    orphans = await cursor.fetchall()
    assert len(orphans) == 0

    # Addresses updated
    cursor = await db.execute("SELECT address FROM agents WHERE id = ?", (agent1_id,))
    assert (await cursor.fetchone())["address"] == "coder@admin.amp.linkyun.co"

    cursor = await db.execute("SELECT address FROM agents WHERE id = ?", (agent2_id,))
    assert (await cursor.fetchone())["address"] == "planner@admin.amp.linkyun.co"

    # Human operator address updated
    cursor = await db.execute("SELECT address FROM agents WHERE name = 'Human Operator'")
    assert (await cursor.fetchone())["address"] == "human-operator@admin.amp.linkyun.co"

    # Messages updated
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    msg = await cursor.fetchone()
    assert msg["from_agent"] == "planner@admin.amp.linkyun.co"
    assert msg["to_agent"] == "coder@admin.amp.linkyun.co"

    # Backup exists
    backups = list(Path(tmp_db).parent.glob("*.bak.*"))
    assert len(backups) == 1

    await db.close()


# --- login / logout ---


@pytest.fixture
async def broker_with_user(tmp_path):
    """Spin up the FastAPI app on an in-memory DB seeded with one user."""
    db = await get_db(":memory:")
    await init_db(db)
    code = await ensure_bootstrap_invite_code(db)

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, "alice", hash_password("secret-pw-123"), 1, now),
    )
    await db.execute(
        "UPDATE invite_codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
        (user_id, now, code),
    )
    await db.commit()
    app.state.db = db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://broker.test") as client:
        yield client
    await db.close()


async def test_login_writes_credentials(broker_with_user, tmp_path):
    creds = tmp_path / "credentials.json"
    args = Args(
        broker_url="http://broker.test",
        username="alice",
        password="secret-pw-123",
        credentials_path=str(creds),
    )
    await _login(args, client=broker_with_user)

    assert creds.exists()
    # Mode 0600 — owner read/write only.
    assert (creds.stat().st_mode & 0o777) == 0o600

    data = json.loads(creds.read_text())
    assert data["default_broker_url"] == "http://broker.test"
    entry = data["credentials"]["http://broker.test"]
    assert entry["username"] == "alice"
    assert isinstance(entry["token"], str) and len(entry["token"]) > 0


async def test_login_bad_password_exits(broker_with_user, tmp_path):
    creds = tmp_path / "credentials.json"
    args = Args(
        broker_url="http://broker.test",
        username="alice",
        password="wrong-password",
        credentials_path=str(creds),
    )
    with pytest.raises(SystemExit):
        await _login(args, client=broker_with_user)
    # No credentials file should be created on a failed login.
    assert not creds.exists()


async def test_login_normalizes_trailing_slash(broker_with_user, tmp_path):
    creds = tmp_path / "credentials.json"
    args = Args(
        broker_url="http://broker.test/",  # trailing slash
        username="alice",
        password="secret-pw-123",
        credentials_path=str(creds),
    )
    await _login(args, client=broker_with_user)

    data = json.loads(creds.read_text())
    # Stored without the trailing slash.
    assert "http://broker.test" in data["credentials"]
    assert "http://broker.test/" not in data["credentials"]


async def test_logout_specific_broker(tmp_path):
    creds = tmp_path / "credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text(json.dumps({
        "default_broker_url": "http://a",
        "credentials": {
            "http://a": {"username": "alice", "token": "t1"},
            "http://b": {"username": "bob", "token": "t2"},
        },
    }))

    await _logout(Args(broker_url="http://a", credentials_path=str(creds)))

    data = json.loads(creds.read_text())
    assert "http://a" not in data["credentials"]
    assert "http://b" in data["credentials"]
    # default flips to the remaining entry.
    assert data["default_broker_url"] == "http://b"


async def test_logout_all_deletes_file(tmp_path):
    creds = tmp_path / "credentials.json"
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text(json.dumps({
        "default_broker_url": "http://a",
        "credentials": {"http://a": {"username": "alice", "token": "t1"}},
    }))

    await _logout(Args(broker_url=None, credentials_path=str(creds)))
    assert not creds.exists()


async def test_load_session_missing_credentials_exits(tmp_path):
    creds = tmp_path / "nonexistent.json"
    args = Args(broker_url="http://broker.test", credentials_path=str(creds))
    with pytest.raises(SystemExit):
        load_session(args)


async def test_load_session_returns_token(broker_with_user, tmp_path):
    creds = tmp_path / "credentials.json"
    args = Args(
        broker_url="http://broker.test",
        username="alice",
        password="secret-pw-123",
        credentials_path=str(creds),
    )
    await _login(args, client=broker_with_user)

    broker_url, entry = load_session(Args(
        broker_url=None,  # falls back to default
        credentials_path=str(creds),
    ))
    assert broker_url == "http://broker.test"
    assert entry["username"] == "alice"
    assert entry["token"]


def test_resolve_broker_url_priorities():
    # 1. CLI flag wins
    assert resolve_broker_url(Args(broker_url="http://flag/"), {}) == "http://flag"
    # 2. Default from creds when no flag
    assert resolve_broker_url(
        Args(broker_url=None),
        {"default_broker_url": "http://saved"},
    ) == "http://saved"
    # 3. Hardcoded fallback when neither
    from agent_mailer.cli import DEFAULT_BROKER_URL
    assert resolve_broker_url(Args(broker_url=None), {}) == DEFAULT_BROKER_URL


# --- cloud shortcuts / default team ---


def test_normalize_team_name():
    assert _normalize_team_name("Demo Team!") == "demo-team"
    assert _normalize_team_name("__") == "team"
    assert _normalize_team_name("-bad") == "bad"


def test_render_default_team_yaml_codex():
    text = _render_default_team_yaml(
        "demo", "http://broker.test", "codex"
    )
    assert "team: demo" in text
    assert "broker_url: http://broker.test" in text
    assert "runtime: codex" in text
    for name in ("demo_planner", "demo_coder", "demo_reviewer", "demo_runner"):
        assert f"name: {name}" in text
    assert "forward 给 demo_coder" in text
    assert "reply 给 demo_reviewer" in text


def test_pyproject_exposes_amp_alias():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    scripts = pyproject["project"]["scripts"]
    assert scripts["agent-mailer"] == "agent_mailer.cli:main"
    assert scripts["amp"] == scripts["agent-mailer"]


@pytest.mark.parametrize(
    "argv",
    [
        ["amp", "init", "--team", "demo", "--broker-url", "http://broker.test"],
        ["amp", "new", "--team", "demo", "--broker-url", "http://broker.test"],
        ["agent-mailer", "cloud", "init", "--team", "demo", "--broker-url", "http://broker.test"],
    ],
)
def test_main_dispatches_cloud_init(monkeypatch, argv):
    calls = []

    async def fake_cloud_init(args):
        calls.append(args)

    monkeypatch.setattr(cli_module, "_cloud_init", fake_cloud_init)
    monkeypatch.setattr(sys, "argv", argv)

    cli_module.main()

    assert len(calls) == 1
    assert calls[0].team == "demo"
    assert calls[0].broker_url == "http://broker.test"


def test_main_dispatches_cloud_init_shortest_form(monkeypatch):
    calls = []

    async def fake_cloud_init(args):
        calls.append(args)

    monkeypatch.setattr(cli_module, "_cloud_init", fake_cloud_init)
    monkeypatch.setattr(sys, "argv", ["amp", "init"])

    cli_module.main()

    assert len(calls) == 1
    assert calls[0].team is None
    assert calls[0].broker_url is None


@pytest.mark.parametrize(
    ("argv", "expected_script"),
    [
        (["amp", "start"], "start-team.sh"),
        (["amp", "stop"], "stop-team.sh"),
        (["agent-mailer", "cloud", "start"], "start-team.sh"),
        (["agent-mailer", "cloud", "stop"], "stop-team.sh"),
    ],
)
def test_main_dispatches_cloud_start_stop(monkeypatch, argv, expected_script):
    calls = []

    def fake_run_script(args, script_name):
        calls.append((args, script_name))

    monkeypatch.setattr(cli_module, "_cloud_run_script", fake_run_script)
    monkeypatch.setattr(sys, "argv", argv)

    cli_module.main()

    assert len(calls) == 1
    assert calls[0][1] == expected_script


def test_cloud_run_script_executes_from_team_dir(monkeypatch, tmp_path):
    script = tmp_path / "start-team.sh"
    script.write_text("#!/usr/bin/env bash\n")
    calls = []

    def fake_run(cmd, cwd, check):
        calls.append((cmd, cwd, check))

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    cli_module._cloud_run_script(Args(dir=str(tmp_path)), "start-team.sh")

    assert calls == [([str(script)], tmp_path.resolve(), True)]


def test_cloud_run_script_missing_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli_module._cloud_run_script(Args(dir=str(tmp_path)), "start-team.sh")
    assert exc_info.value.code == 1
    assert "amp init" in capsys.readouterr().err


async def test_cloud_init_writes_default_codex_team(broker_with_user, tmp_path):
    out = tmp_path / "cloud-team"
    creds = tmp_path / "credentials.json"

    await _cloud_init(
        Args(
            team="demo",
            dir=str(out),
            broker_url="http://broker.test",
            username="alice",
            password="secret-pw-123",
            runtime="codex",
            force=False,
            credentials_path=str(creds),
        ),
        client=broker_with_user,
    )

    assert (out / "team.yaml").exists()
    assert "name: demo_planner" in (out / "team.yaml").read_text()
    for name in ("demo_planner", "demo_coder", "demo_reviewer", "demo_runner"):
        ad = out / "agents" / name
        assert (ad / "AGENT.md").exists()
        assert (ad / ".env").exists()

    assert (out / "start-team.sh").exists()
    assert (out / "stop-team.sh").exists()
    ticks = out / ".agent-mailer" / "codex-ticks.json"
    assert ticks.exists()
    cfg = json.loads(ticks.read_text())
    assert {a["name"] for a in cfg["agents"]} == {
        "demo_planner",
        "demo_coder",
        "demo_reviewer",
        "demo_runner",
    }


async def test_cloud_init_uses_saved_default_broker(broker_with_user, tmp_path):
    token = await _login_and_get_token(
        broker_with_user, "http://broker.test", "alice", "secret-pw-123"
    )
    creds = tmp_path / "credentials.json"
    _write_credentials(creds, "http://broker.test", token)
    out = tmp_path / "saved-broker-team"

    await _cloud_init(
        Args(
            team="saved",
            dir=str(out),
            broker_url=None,
            username=None,
            password=None,
            runtime="codex",
            force=False,
            credentials_path=str(creds),
        ),
        client=broker_with_user,
    )

    assert "broker_url: http://broker.test" in (out / "team.yaml").read_text()


async def test_cloud_init_requires_login_noninteractive(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_module.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as exc_info:
        await _cloud_init(
            Args(
                team="demo",
                dir=str(tmp_path / "team"),
                broker_url="http://broker.test",
                username=None,
                password=None,
                runtime="codex",
                force=False,
                credentials_path=str(tmp_path / "missing.json"),
            )
        )
    assert exc_info.value.code == 1
    assert "amp login --broker-url http://broker.test" in capsys.readouterr().err


# --- up-team ---


def _write_team_yaml(path: Path, body: str) -> None:
    path.write_text(body)


def _write_credentials(creds_path: Path, broker_url: str, token: str, username: str = "alice") -> None:
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(json.dumps({
        "default_broker_url": broker_url,
        "credentials": {broker_url: {"username": username, "token": token}},
    }))


async def _login_and_get_token(client, broker_url: str, username: str, password: str) -> str:
    resp = await client.post(
        f"{broker_url}/users/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_validate_team_spec_minimal():
    spec = _validate_team_spec({
        "team": "Squad",
        "agents": [{"name": "planner", "system_prompt": "."}],
    })
    assert spec["team"] == "Squad"
    assert spec["agents"][0]["runtime"] == "claude"  # default


def test_validate_team_spec_runtime_override():
    spec = _validate_team_spec({
        "team": "Mixed",
        "defaults": {"runtime": "claude"},
        "agents": [
            {"name": "a", "system_prompt": "."},
            {"name": "b", "runtime": "codex", "system_prompt": "."},
        ],
    })
    assert spec["agents"][0]["runtime"] == "claude"
    assert spec["agents"][1]["runtime"] == "codex"


def test_validate_team_spec_rejects_missing_team():
    with pytest.raises(ValueError, match="team"):
        _validate_team_spec({"agents": [{"name": "a", "system_prompt": "."}]})


def test_validate_team_spec_rejects_empty_agents():
    with pytest.raises(ValueError, match="agents"):
        _validate_team_spec({"team": "X", "agents": []})


def test_validate_team_spec_rejects_invalid_runtime():
    with pytest.raises(ValueError, match="runtime"):
        _validate_team_spec({
            "team": "X",
            "agents": [{"name": "a", "runtime": "bash", "system_prompt": "."}],
        })


async def test_up_team_writes_all_artifacts(broker_with_user, tmp_path):
    token = await _login_and_get_token(
        broker_with_user, "http://broker.test", "alice", "secret-pw-123"
    )
    creds = tmp_path / "credentials.json"
    _write_credentials(creds, "http://broker.test", token)

    out = tmp_path / "proj"
    out.mkdir()
    yaml_path = out / "team.yaml"
    _write_team_yaml(yaml_path, """
team: TestSquad
agents:
  - name: planner
    role: planner
    system_prompt: I plan.
  - name: coder
    role: coder
    runtime: codex
    system_prompt: I code.
""")

    await _up_team(
        Args(
            yaml_path=str(yaml_path),
            broker_url=None,
            output_dir=str(out),
            credentials_path=str(creds),
        ),
        client=broker_with_user,
    )

    # Per-agent directories with AGENT.md and .env
    for name in ("planner", "coder"):
        ad = out / "agents" / name
        assert (ad / "AGENT.md").exists()
        env = ad / ".env"
        assert env.exists()
        assert (env.stat().st_mode & 0o777) == 0o600
        env_text = env.read_text()
        assert "AMP_API_KEY=amk_" in env_text
        assert "AMP_BROKER_URL=http://broker.test" in env_text
        assert f"AMP_AGENT_ADDRESS={name}@" in env_text
        # AGENT.md uses the env var placeholder, never the inline one.
        md = (ad / "AGENT.md").read_text()
        assert "${AMP_API_KEY}" in md
        assert "<your_api_key>" not in md

    # Launcher scripts
    start = (out / "start-team.sh").read_text()
    assert (out / "start-team.sh").stat().st_mode & 0o111  # executable
    assert "agent-mailer-TestSquad" in start
    # claude pane uses the bypass flag so autonomous agents don't deadlock on
    # tool-permission prompts.
    assert 'claude --dangerously-skip-permissions "上班"' in start
    # Trust pre-acceptance + bypass-dialog dismissal must be wired up.
    assert "hasTrustDialogAccepted" in start
    assert "Yes, I accept" in start
    assert "codex" in start  # codex agent present
    assert (out / "stop-team.sh").exists()
    assert (out / "stop-team.sh").stat().st_mode & 0o111

    # Codex tick daemon config: written iff at least one codex agent exists.
    ticks = out / ".agent-mailer" / "codex-ticks.json"
    assert ticks.exists()
    cfg = json.loads(ticks.read_text())
    coder_entry = next(a for a in cfg["agents"] if a["name"] == "coder")
    assert coder_entry["pane"] == "agent-mailer-TestSquad:coder"
    assert Path(coder_entry["agent_dir"]).resolve() == (out / "agents" / "coder").resolve()
    # Only codex agents listed; the claude one stays out.
    assert all(a["name"] != "planner" for a in cfg["agents"])

    # start-team.sh wires up daemon launch and stop-team.sh wires up daemon kill.
    assert "codex-tick" in start
    assert ".agent-mailer/codex-tick.pid" in start
    stop = (out / "stop-team.sh").read_text()
    assert "codex-tick.pid" in stop


async def test_up_team_pure_claude_skips_codex_artifacts(broker_with_user, tmp_path):
    token = await _login_and_get_token(
        broker_with_user, "http://broker.test", "alice", "secret-pw-123"
    )
    creds = tmp_path / "credentials.json"
    _write_credentials(creds, "http://broker.test", token)

    out = tmp_path / "proj"
    out.mkdir()
    (out / "team.yaml").write_text("""
team: PureClaude
agents:
  - name: solo
    system_prompt: .
""")
    await _up_team(
        Args(
            yaml_path=str(out / "team.yaml"),
            broker_url=None,
            output_dir=str(out),
            credentials_path=str(creds),
        ),
        client=broker_with_user,
    )
    # No codex → no daemon artifact and stop script doesn't reference it.
    assert not (out / ".agent-mailer" / "codex-ticks.json").exists()
    stop = (out / "stop-team.sh").read_text()
    assert "codex-tick" not in stop
    start = (out / "start-team.sh").read_text()
    assert "codex-tick" not in start

    # .gitignore appended idempotently
    gi = (out / ".gitignore").read_text()
    assert "agents/" in gi
    assert "start-team.sh" in gi
    assert ".agent-mailer/" in gi

    # Re-running doesn't duplicate the entries (idempotency check).
    # Bootstrap will fail on duplicate team name, but the gitignore update happens
    # before the bootstrap call... actually no, after success. So can't easily
    # test re-run here. Instead, call _update_gitignore directly.
    from agent_mailer.cli import _update_gitignore
    _update_gitignore(out)
    gi_after = (out / ".gitignore").read_text()
    assert gi_after.count("agents/") == 1
    assert gi_after.count("start-team.sh") == 1


async def test_up_team_yaml_validation_error_does_not_call_broker(broker_with_user, tmp_path):
    # Even without credentials, an invalid YAML should fail before any network call.
    yaml_path = tmp_path / "team.yaml"
    yaml_path.write_text("team: BadYaml\nagents: []\n")
    with pytest.raises(SystemExit):
        await _up_team(
            Args(
                yaml_path=str(yaml_path),
                broker_url="http://broker.test",
                output_dir=str(tmp_path / "proj"),
                credentials_path=str(tmp_path / "credentials.json"),
            ),
            client=broker_with_user,
        )
    # Nothing was created.
    assert not (tmp_path / "proj").exists() or not any((tmp_path / "proj").iterdir())


async def test_up_team_missing_credentials(broker_with_user, tmp_path):
    yaml_path = tmp_path / "team.yaml"
    yaml_path.write_text("""
team: Squad
agents:
  - name: a
    system_prompt: .
""")
    with pytest.raises(SystemExit):
        await _up_team(
            Args(
                yaml_path=str(yaml_path),
                broker_url="http://broker.test",
                output_dir=str(tmp_path / "proj"),
                credentials_path=str(tmp_path / "credentials.json"),  # missing
            ),
            client=broker_with_user,
        )


async def test_up_team_409_team_name_collision(broker_with_user, tmp_path):
    token = await _login_and_get_token(
        broker_with_user, "http://broker.test", "alice", "secret-pw-123"
    )
    creds = tmp_path / "credentials.json"
    _write_credentials(creds, "http://broker.test", token)

    yaml_path = tmp_path / "team.yaml"
    yaml_path.write_text("""
team: Dup
agents:
  - name: a
    system_prompt: .
""")
    args = Args(
        yaml_path=str(yaml_path),
        broker_url=None,
        output_dir=str(tmp_path / "proj"),
        credentials_path=str(creds),
    )
    # First call succeeds.
    await _up_team(args, client=broker_with_user)
    # Second call hits 409 from broker and exits.
    with pytest.raises(SystemExit):
        await _up_team(args, client=broker_with_user)
