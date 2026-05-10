import os

os.environ.setdefault(
    "AGENT_MAILER_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-bytes-long",
)

import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_mailer.auth import hash_password, verify_password
from agent_mailer.cli import _bootstrap_admin, _generate_invite_code, _migrate_db
from agent_mailer.db import get_db, init_db


class Args:
    """Simple namespace to mimic argparse output."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture
async def tmp_db(tmp_path):
    db_file = str(tmp_path / "test.db")
    db = await get_db(db_file)
    await init_db(db)
    await db.close()
    return db_file


def test_pyproject_cli_scripts() -> None:
    scripts = tomllib.loads(Path("pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["agent-mailer-server"] == "agent_mailer.cli:main"
    assert scripts["agent-mailer"] == "agent_mailer_cli.main:cli"
    assert scripts["amp"] == "agent_mailer_cli.amp:cli"


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
    await _bootstrap_admin(Args(db=tmp_db, username="admin1", password="password12345678"))

    with pytest.raises(SystemExit) as exc_info:
        await _bootstrap_admin(Args(db=tmp_db, username="admin2", password="password12345678"))
    assert exc_info.value.code == 1


async def test_generate_invite_code_success(tmp_db, capsys):
    await _bootstrap_admin(Args(db=tmp_db, username="admin", password="adminpass1234"))

    await _generate_invite_code(Args(db=tmp_db, username="admin", password="adminpass1234"))

    captured = capsys.readouterr()
    assert "Invite code:" in captured.out
    code = next(
        line.split(": ", 1)[1].strip()
        for line in captured.out.strip().split("\n")
        if line.startswith("Invite code:")
    )
    assert len(code) == 8

    db = await get_db(tmp_db)
    cursor = await db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["used_by"] is None
    await db.close()


async def test_generate_invite_code_wrong_password(tmp_db):
    await _bootstrap_admin(Args(db=tmp_db, username="admin", password="adminpass1234"))

    with pytest.raises(SystemExit) as exc_info:
        await _generate_invite_code(Args(db=tmp_db, username="admin", password="wrongpass"))
    assert exc_info.value.code == 1


async def test_generate_invite_code_non_superadmin(tmp_db):
    await _bootstrap_admin(Args(db=tmp_db, username="admin", password="adminpass1234"))

    db = await get_db(tmp_db)
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "regular", hash_password("regularpass12"), 0, now),
    )
    await db.commit()
    await db.close()

    with pytest.raises(SystemExit) as exc_info:
        await _generate_invite_code(Args(db=tmp_db, username="regular", password="regularpass12"))
    assert exc_info.value.code == 1


async def test_migrate_db(tmp_db, capsys):
    db = await get_db(tmp_db)
    now = datetime.now(timezone.utc).isoformat()
    agent1_id = str(uuid.uuid4())
    agent2_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent1_id, "coder", "coder@local", "coder", "A coder", now),
    )
    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent2_id, "planner", "planner@local", "planner", "A planner", now),
    )

    msg_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, thread_id, "planner@local", "coder@local", "send", "Task", "Do this", now),
    )
    await db.execute(
        "INSERT INTO agents (id, name, address, role, system_prompt, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "00000000-0000-0000-0000-000000000000",
            "Human Operator",
            "human-operator@local",
            "operator",
            "",
            now,
        ),
    )
    await db.commit()
    await db.close()

    await _migrate_db(Args(db=tmp_db, password="migrate-pass-123"))

    captured = capsys.readouterr()
    assert "Migration complete" in captured.out
    assert "Backup created" in captured.out

    db = await get_db(tmp_db)
    cursor = await db.execute("SELECT * FROM users WHERE username = 'admin'")
    admin = await cursor.fetchone()
    assert admin is not None
    assert admin["is_superadmin"] == 1

    cursor = await db.execute("SELECT * FROM agents WHERE user_id IS NULL")
    assert await cursor.fetchall() == []

    cursor = await db.execute("SELECT address FROM agents WHERE id = ?", (agent1_id,))
    assert (await cursor.fetchone())["address"] == "coder@admin.amp.linkyun.co"
    cursor = await db.execute("SELECT address FROM agents WHERE id = ?", (agent2_id,))
    assert (await cursor.fetchone())["address"] == "planner@admin.amp.linkyun.co"
    cursor = await db.execute("SELECT address FROM agents WHERE name = 'Human Operator'")
    assert (await cursor.fetchone())["address"] == "human-operator@admin.amp.linkyun.co"

    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    msg = await cursor.fetchone()
    assert msg["from_agent"] == "planner@admin.amp.linkyun.co"
    assert msg["to_agent"] == "coder@admin.amp.linkyun.co"
    assert len(list(Path(tmp_db).parent.glob("*.bak.*"))) == 1

    await db.close()
