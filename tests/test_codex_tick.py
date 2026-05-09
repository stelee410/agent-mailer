"""Tests for the agent-mailer-codex-tick daemon."""

import os

os.environ.setdefault(
    "AGENT_MAILER_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-bytes-long",
)

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_mailer.auth import generate_api_key, hash_password
from agent_mailer.codex_tick import (
    has_unread,
    load_config,
    main_loop,
    parse_env_file,
    tick_one,
)
from agent_mailer.db import get_db, init_db
from agent_mailer.main import app


# --- parse_env_file ---


def test_parse_env_file_basic(tmp_path):
    p = tmp_path / ".env"
    p.write_text("AMP_API_KEY=amk_abc\nAMP_BROKER_URL=http://localhost:9800\n")
    out = parse_env_file(p)
    assert out == {"AMP_API_KEY": "amk_abc", "AMP_BROKER_URL": "http://localhost:9800"}


def test_parse_env_file_skips_comments_and_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# a comment\n\nKEY=value\n   # another\n")
    assert parse_env_file(p) == {"KEY": "value"}


def test_parse_env_file_strips_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('A="quoted"\nB=\'single\'\nC=plain\n')
    assert parse_env_file(p) == {"A": "quoted", "B": "single", "C": "plain"}


def test_parse_env_file_missing(tmp_path):
    assert parse_env_file(tmp_path / "does-not-exist") == {}


# --- load_config ---


def test_load_config_missing(tmp_path):
    assert load_config(tmp_path / "missing.json") == []


def test_load_config_invalid_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json {{{")
    assert load_config(p) == []


def test_load_config_valid(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"agents": [{"name": "a"}, {"name": "b"}]}))
    assert load_config(p) == [{"name": "a"}, {"name": "b"}]


# --- has_unread (against the live FastAPI app) ---


@pytest.fixture
async def broker_with_agent():
    """Provision one user, one agent (with API key) and yield (httpx client, agent dict)."""
    db = await get_db(":memory:")
    await init_db(db)

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, "alice", hash_password("pw"), 1, now),
    )

    agent_id = str(uuid.uuid4())
    raw_key, key_hash = generate_api_key()
    address = f"coder@alice.amp.linkyun.co"
    await db.execute(
        "INSERT INTO agents (id, name, address, role, description, system_prompt, "
        "tags, user_id, created_at, status, api_key_suffix) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (agent_id, "coder", address, "coder", "", "", "[]", user_id, now, raw_key[-6:]),
    )
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (str(uuid.uuid4()), user_id, key_hash, f"agent:{agent_id}", now),
    )
    # Sender for inbox population.
    sender_id = str(uuid.uuid4())
    sender_addr = "sender@alice.amp.linkyun.co"
    await db.execute(
        "INSERT INTO agents (id, name, address, role, description, system_prompt, "
        "tags, user_id, created_at, status, api_key_suffix) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (sender_id, "sender", sender_addr, "human", "", "", "[]", user_id, now, raw_key[-6:]),
    )
    await db.commit()
    app.state.db = db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://broker.test") as c:
        yield c, {
            "address": address,
            "agent_id": agent_id,
            "api_key": raw_key,
            "sender_address": sender_addr,
            "broker_url": "http://broker.test",
        }
    await db.close()


async def test_has_unread_empty_inbox(broker_with_agent):
    client, info = broker_with_agent
    assert await has_unread(
        info["broker_url"], info["address"], info["agent_id"], info["api_key"],
        client=client,
    ) is False


async def test_has_unread_with_pending_message(broker_with_agent):
    client, info = broker_with_agent
    # Send a message to the agent's inbox.
    resp = await client.post(
        "/messages/send",
        headers={"X-API-Key": info["api_key"]},
        json={
            "agent_id": info["agent_id"],  # the API key's owner is the user; broker checks tenancy via user_id
            "from_agent": info["sender_address"],
            "to_agent": info["address"],
            "action": "send",
            "subject": "wakeup",
            "body": "please tick",
        },
    )
    # We're sending from a "different" agent; the broker requires the sender's
    # agent_id, not the recipient's. Look up via the sender's row.
    if resp.status_code != 200:
        # Need the sender's agent_id — adapt the request.
        # Easier path: post a synthetic message directly via DB. The test is about the
        # *daemon* observing unread, not about /messages/send semantics.
        from agent_mailer.main import app as _app
        db = _app.state.db
        await db.execute(
            "INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, "
            "attachments, is_read, parent_id, created_at) "
            "VALUES (?, ?, ?, ?, 'send', 'wakeup', 'please tick', '[]', 0, NULL, ?)",
            (str(uuid.uuid4()), str(uuid.uuid4()), info["sender_address"], info["address"],
             datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()

    assert await has_unread(
        info["broker_url"], info["address"], info["agent_id"], info["api_key"],
        client=client,
    ) is True


async def test_has_unread_bad_credentials(broker_with_agent):
    client, info = broker_with_agent
    assert await has_unread(
        info["broker_url"], info["address"], info["agent_id"], "amk_wrong",
        client=client,
    ) is False


# --- tick_one ---


async def test_tick_one_skip_when_inbox_empty(broker_with_agent, tmp_path):
    client, info = broker_with_agent
    # Lay down a fake .env mirroring what up-team would write.
    agent_dir = tmp_path / "agents" / "coder"
    agent_dir.mkdir(parents=True)
    (agent_dir / ".env").write_text(
        f"AMP_API_KEY={info['api_key']}\n"
        f"AMP_BROKER_URL={info['broker_url']}\n"
        f"AMP_AGENT_ADDRESS={info['address']}\n"
        f"AMP_AGENT_ID={info['agent_id']}\n"
    )
    # tmux helpers should never be invoked in this branch.
    sent = []
    outcome = await tick_one(
        {"name": "coder", "agent_dir": str(agent_dir), "pane": "fake:coder"},
        client=client,
        tmux_send=lambda t, k: sent.append((t, k)),
        tmux_idle=lambda t: True,
    )
    assert outcome == "skip:empty-inbox"
    assert sent == []


async def test_tick_one_sends_when_inbox_pending_and_pane_idle(broker_with_agent, tmp_path):
    client, info = broker_with_agent
    # Plant an unread message via DB.
    db = app.state.db
    await db.execute(
        "INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, "
        "attachments, is_read, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, 'send', 'go', 'work please', '[]', 0, NULL, ?)",
        (str(uuid.uuid4()), str(uuid.uuid4()), info["sender_address"], info["address"],
         datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    agent_dir = tmp_path / "agents" / "coder"
    agent_dir.mkdir(parents=True)
    (agent_dir / ".env").write_text(
        f"AMP_API_KEY={info['api_key']}\n"
        f"AMP_BROKER_URL={info['broker_url']}\n"
        f"AMP_AGENT_ADDRESS={info['address']}\n"
        f"AMP_AGENT_ID={info['agent_id']}\n"
    )

    sent = []
    outcome = await tick_one(
        {"name": "coder", "agent_dir": str(agent_dir), "pane": "fake:coder"},
        client=client,
        tmux_send=lambda t, k: sent.append((t, k)),
        tmux_idle=lambda t: True,
    )
    assert outcome == "sent"
    assert sent == [("fake:coder", "查收")]


async def test_tick_one_skip_when_pane_busy(broker_with_agent, tmp_path):
    client, info = broker_with_agent
    db = app.state.db
    await db.execute(
        "INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, "
        "attachments, is_read, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, 'send', 'go', 'work please', '[]', 0, NULL, ?)",
        (str(uuid.uuid4()), str(uuid.uuid4()), info["sender_address"], info["address"],
         datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    agent_dir = tmp_path / "agents" / "coder"
    agent_dir.mkdir(parents=True)
    (agent_dir / ".env").write_text(
        f"AMP_API_KEY={info['api_key']}\n"
        f"AMP_BROKER_URL={info['broker_url']}\n"
        f"AMP_AGENT_ADDRESS={info['address']}\n"
        f"AMP_AGENT_ID={info['agent_id']}\n"
    )

    sent = []
    outcome = await tick_one(
        {"name": "coder", "agent_dir": str(agent_dir), "pane": "fake:coder"},
        client=client,
        tmux_send=lambda t, k: sent.append((t, k)),
        tmux_idle=lambda t: False,  # pane reports busy
    )
    assert outcome == "skip:pane-busy"
    assert sent == []


async def test_tick_one_skip_on_bad_env(tmp_path):
    agent_dir = tmp_path / "agents" / "broken"
    agent_dir.mkdir(parents=True)
    (agent_dir / ".env").write_text("AMP_API_KEY=only-this\n")  # missing other vars

    outcome = await tick_one(
        {"name": "broken", "agent_dir": str(agent_dir), "pane": "fake:broken"},
        tmux_send=lambda *a: None,
        tmux_idle=lambda t: True,
    )
    assert outcome == "skip:bad-env"


# --- main_loop exit condition ---


async def test_main_loop_exits_when_no_agents(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": []}))
    logs: list[str] = []
    await main_loop(cfg, interval=60.0, log=logs.append)
    assert any("no agents" in line for line in logs)


async def test_main_loop_exits_when_config_missing(tmp_path):
    cfg = tmp_path / "missing.json"
    logs: list[str] = []
    await main_loop(cfg, interval=60.0, log=logs.append)
    assert any("no agents" in line for line in logs)
