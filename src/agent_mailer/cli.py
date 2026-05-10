import argparse
import asyncio
import secrets
import shutil
import string
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent_mailer.auth import hash_password, verify_password
from agent_mailer.config import DOMAIN
from agent_mailer.db import DB_PATH, get_db, init_db


INVITE_CODE_CHARS = string.ascii_letters + string.digits
INVITE_CODE_LENGTH = 8


async def _bootstrap_admin(args):
    db = await get_db(args.db)
    await init_db(db)

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        print("Error: Users already exist. bootstrap-admin is only for first-time setup.")
        await db.close()
        sys.exit(1)

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, args.username, hash_password(args.password), 1, now),
    )
    await db.commit()
    await db.close()
    print(f"Superadmin user '{args.username}' created successfully.")
    print(f"User ID: {user_id}")


async def _generate_invite_code(args):
    db = await get_db(args.db)
    await init_db(db)

    cursor = await db.execute(
        "SELECT * FROM users WHERE username = ?", (args.username,)
    )
    user = await cursor.fetchone()
    if not user:
        print(f"Error: User '{args.username}' not found.")
        await db.close()
        sys.exit(1)

    if not verify_password(args.password, user["password_hash"]):
        print("Error: Invalid password.")
        await db.close()
        sys.exit(1)

    if not user["is_superadmin"]:
        print("Error: Only superadmin users can generate invite codes.")
        await db.close()
        sys.exit(1)

    code = "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(INVITE_CODE_LENGTH))
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO invite_codes (code, created_by, created_at) VALUES (?, ?, ?)",
        (code, user["id"], now),
    )
    await db.commit()
    await db.close()
    print(f"Invite code: {code}")


async def _migrate_db(args):
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database file '{args.db}' not found.")
        sys.exit(1)

    # 1. Backup
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{args.db}.bak.{timestamp}"
    shutil.copy2(args.db, backup_path)
    print(f"Backup created: {backup_path}")

    db = await get_db(args.db)
    await init_db(db)

    # 2. Create or find admin user
    username = "admin"
    domain_suffix = f"@{username}.{DOMAIN}"

    cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
    admin_user = await cursor.fetchone()
    if admin_user:
        admin_id = admin_user["id"]
        print(f"Using existing admin user: {admin_id}")
    else:
        admin_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
            (admin_id, username, hash_password(args.password), 1, now),
        )
        print(f"Created admin user: {admin_id}")

    # 3. Associate orphan agents
    cursor = await db.execute(
        "UPDATE agents SET user_id = ? WHERE user_id IS NULL", (admin_id,)
    )
    agents_updated = cursor.rowcount
    print(f"Agents associated with admin: {agents_updated}")

    # 4. Update agent addresses: {name}@local → {name}@admin.amp.linkyun.co
    cursor = await db.execute(
        "SELECT id, name, address FROM agents WHERE address LIKE '%@local'"
    )
    agents_to_rename = await cursor.fetchall()
    msg_from_updated = 0
    msg_to_updated = 0
    for agent in agents_to_rename:
        old_addr = agent["address"]
        # Extract the part before @local
        local_part = old_addr.split("@")[0]
        new_addr = f"{local_part}{domain_suffix}"
        await db.execute("UPDATE agents SET address = ? WHERE id = ?", (new_addr, agent["id"]))
        # 5. Update messages
        c1 = await db.execute(
            "UPDATE messages SET from_agent = ? WHERE from_agent = ?",
            (new_addr, old_addr),
        )
        msg_from_updated += c1.rowcount
        c2 = await db.execute(
            "UPDATE messages SET to_agent = ? WHERE to_agent = ?",
            (new_addr, old_addr),
        )
        msg_to_updated += c2.rowcount

    await db.commit()
    await db.close()

    print(f"Addresses updated: {len(agents_to_rename)} agents")
    print(f"Messages updated: {msg_from_updated} from_agent, {msg_to_updated} to_agent")
    print("Migration complete.")


def main():
    parser = argparse.ArgumentParser(prog="agent-mailer-server", description="Agent Mailer Broker CLI")
    parser.add_argument("--db", default=DB_PATH, help="Database file path")
    subparsers = parser.add_subparsers(dest="command")

    # bootstrap-admin
    bp = subparsers.add_parser("bootstrap-admin", help="Create first superadmin user")
    bp.add_argument("--username", required=True, help="Admin username")
    bp.add_argument("--password", required=True, help="Admin password")

    # generate-invite-code
    gi = subparsers.add_parser("generate-invite-code", help="Generate an invite code")
    gi.add_argument("--username", required=True, help="Superadmin username")
    gi.add_argument("--password", required=True, help="Superadmin password")

    # migrate-db
    md = subparsers.add_parser("migrate-db", help="Migrate local-mode DB to SaaS mode")
    md.add_argument("--password", required=True, help="Password for the admin user")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "bootstrap-admin":
        asyncio.run(_bootstrap_admin(args))
    elif args.command == "generate-invite-code":
        asyncio.run(_generate_invite_code(args))
    elif args.command == "migrate-db":
        asyncio.run(_migrate_db(args))


if __name__ == "__main__":
    main()
