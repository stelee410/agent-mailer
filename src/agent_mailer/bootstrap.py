import os
import secrets
import string
from datetime import datetime, timezone


BOOTSTRAP_CODE_CHARS = string.ascii_letters + string.digits
BOOTSTRAP_CODE_LENGTH = 8
BOOTSTRAP_CREATOR_ID = "00000000-0000-0000-0000-000000000000"


async def ensure_bootstrap_invite_code(db) -> str | None:
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        return None

    # Check if a bootstrap code already exists (unused)
    cursor = await db.execute(
        "SELECT code FROM invite_codes WHERE created_by = ? AND used_by IS NULL",
        (BOOTSTRAP_CREATOR_ID,),
    )
    existing = await cursor.fetchone()
    if existing:
        code = existing["code"]
    else:
        code = "".join(
            secrets.choice(BOOTSTRAP_CODE_CHARS) for _ in range(BOOTSTRAP_CODE_LENGTH)
        )
        now = datetime.now(timezone.utc).isoformat()
        is_sqlite = not os.environ.get("DATABASE_URL")
        if is_sqlite:
            await db.execute("PRAGMA foreign_keys = OFF")
        try:
            await db.execute(
                "INSERT INTO invite_codes (code, created_by, created_at) VALUES (?, ?, ?)",
                (code, BOOTSTRAP_CREATOR_ID, now),
            )
            await db.commit()
        finally:
            if is_sqlite:
                await db.execute("PRAGMA foreign_keys = ON")

    print(f"\n⚠️  No users found. Bootstrap invite code: {code}")
    print("Use this code to register the first superadmin user.\n")
    return code
