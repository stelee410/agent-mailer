"""Database abstraction layer — supports SQLite (aiosqlite) and PostgreSQL (asyncpg)."""

from __future__ import annotations

import os
import re

DB_PATH = "agent_mailer.db"

# --- Schema (PostgreSQL-compatible DDL) ---

PG_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT NOT NULL UNIQUE,
        role TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        system_prompt TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        user_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        from_agent TEXT NOT NULL,
        to_agent TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('send', 'reply', 'forward')),
        subject TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        attachments TEXT NOT NULL DEFAULT '[]',
        is_read INTEGER NOT NULL DEFAULT 0,
        parent_id TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (parent_id) REFERENCES messages(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archived_threads (
        thread_id TEXT PRIMARY KEY,
        archived_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trashed_threads (
        thread_id TEXT PRIMARY KEY,
        trashed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trashed_messages (
        message_id TEXT PRIMARY KEY,
        trashed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_superadmin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        filter_tags TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invite_codes (
        code TEXT PRIMARY KEY,
        created_by TEXT NOT NULL,
        used_by TEXT,
        used_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        key_hash TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size INTEGER NOT NULL,
        stored_path TEXT NOT NULL,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]

# SQLite-only legacy schema (for CREATE TABLE IF NOT EXISTS + additive migrations)
SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('send', 'reply', 'forward')),
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    attachments TEXT NOT NULL DEFAULT '[]',
    is_read INTEGER NOT NULL DEFAULT 0,
    parent_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES messages(id)
);
"""

ARCHIVED_THREADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS archived_threads (
    thread_id TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL
);
"""

TRASHED_THREADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trashed_threads (
    thread_id TEXT PRIMARY KEY,
    trashed_at TEXT NOT NULL
);
"""

TRASHED_MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trashed_messages (
    message_id TEXT PRIMARY KEY,
    trashed_at TEXT NOT NULL
);
"""

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_superadmin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

INVITE_CODES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    used_by TEXT,
    used_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (used_by) REFERENCES users(id)
);
"""

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# --- Visibility SQL filters ---

INBOX_THREAD_VISIBILITY_SQL = (
    "thread_id NOT IN (SELECT thread_id FROM archived_threads) "
    "AND thread_id NOT IN (SELECT thread_id FROM trashed_threads)"
)

MESSAGE_NOT_TRASHED_SQL = "id NOT IN (SELECT message_id FROM trashed_messages)"

INBOX_VISIBILITY_SQL = f"({INBOX_THREAD_VISIBILITY_SQL}) AND ({MESSAGE_NOT_TRASHED_SQL})"

MESSAGE_ROW_VISIBLE_SQL = "m.id NOT IN (SELECT message_id FROM trashed_messages)"


# ── Placeholder conversion ──────────────────────────────────────────

_Q_RE = re.compile(r"\?")


def _sqlite_to_pg(sql: str) -> str:
    """Convert ``?`` positional placeholders to ``$1, $2, ...``."""
    counter = 0

    def _repl(_match):
        nonlocal counter
        counter += 1
        return f"${counter}"

    return _Q_RE.sub(_repl, sql)


# ── Unified cursor wrapper ──────────────────────────────────────────

class _PgCursorWrapper:
    """Wraps asyncpg results to look like aiosqlite cursors."""

    def __init__(self, rows=None, *, columns=None, rowcount=0):
        self._rows = rows or []
        self._columns = columns or []
        self._idx = 0
        self.rowcount = rowcount

    async def fetchone(self):
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return _PgRowWrapper(row, self._columns)
        return None

    async def fetchall(self):
        remaining = self._rows[self._idx:]
        self._idx = len(self._rows)
        return [_PgRowWrapper(r, self._columns) for r in remaining]


class _PgRowWrapper:
    """Makes an asyncpg Record behave like an aiosqlite.Row (dict-like)."""

    def __init__(self, record, columns=None):
        if isinstance(record, dict):
            self._data = record
        else:
            # asyncpg Record
            self._data = dict(record)

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key, default=None):
        return self._data.get(key, default)


# ── PostgreSQL connection wrapper ───────────────────────────────────

class PgConnectionWrapper:
    """Wraps an asyncpg pool to provide an aiosqlite-compatible interface."""

    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql: str, params=None):
        pg_sql = _sqlite_to_pg(sql)
        args = tuple(params) if params else ()
        sql_upper = sql.strip().upper()

        async with self._pool.acquire() as conn:
            if sql_upper.startswith(("INSERT", "UPDATE", "DELETE")):
                status = await conn.execute(pg_sql, *args)
                # Parse rowcount from status like "UPDATE 3"
                rowcount = 0
                if status:
                    parts = status.split()
                    if len(parts) >= 2 and parts[-1].isdigit():
                        rowcount = int(parts[-1])
                    elif status == "INSERT 0 1":
                        rowcount = 1
                return _PgCursorWrapper(rowcount=rowcount)
            else:
                rows = await conn.fetch(pg_sql, *args)
                columns = list(rows[0].keys()) if rows else []
                return _PgCursorWrapper(rows, columns=columns, rowcount=len(rows))

    async def executescript(self, sql: str):
        """Execute multiple statements (for schema creation)."""
        async with self._pool.acquire() as conn:
            await conn.execute(sql)

    async def commit(self):
        pass  # asyncpg auto-commits

    async def close(self):
        await self._pool.close()


# ── Factory functions ───────────────────────────────────────────────

def _get_database_url() -> str | None:
    """Return DATABASE_URL if set, else None (use SQLite)."""
    return os.environ.get("DATABASE_URL")


async def get_db(db_path: str = DB_PATH):
    """Return a database connection — PostgreSQL if DATABASE_URL is set, else SQLite."""
    database_url = _get_database_url()
    if database_url:
        import asyncpg
        pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        return PgConnectionWrapper(pool)
    else:
        import aiosqlite
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        return db


async def _add_column_if_missing(db, table: str, column: str, col_def: str):
    """Additive migration helper — silently skips if column already exists."""
    database_url = _get_database_url()
    if database_url:
        # PostgreSQL: check information_schema
        try:
            cursor = await db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
                (table, column),
            )
            row = await cursor.fetchone()
            if not row:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        except Exception:
            pass  # column likely exists
    else:
        import sqlite3
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise


async def init_db(db):
    """Initialize schema — works for both SQLite and PostgreSQL."""
    database_url = _get_database_url()
    if database_url:
        for stmt in PG_SCHEMA:
            await db.execute(stmt.strip())
    else:
        await db.executescript(SCHEMA)
        await db.executescript(ARCHIVED_THREADS_SCHEMA)
        await db.executescript(TRASHED_THREADS_SCHEMA)
        await db.executescript(TRASHED_MESSAGES_SCHEMA)
        await db.executescript(USERS_SCHEMA)
        await db.executescript(INVITE_CODES_SCHEMA)
        await db.executescript(API_KEYS_SCHEMA)
        await db.executescript(FILES_SCHEMA)
        await _add_column_if_missing(db, "agents", "tags", "TEXT NOT NULL DEFAULT '[]'")
        await _add_column_if_missing(db, "agents", "user_id", "TEXT")
        await _add_column_if_missing(db, "users", "filter_tags", "TEXT NOT NULL DEFAULT '[]'")
    await db.commit()
