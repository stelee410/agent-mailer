import pytest

from agent_mailer.db import PgConnectionWrapper, db_transaction, init_db, get_db


async def test_init_creates_tables():
    db = await get_db(":memory:")
    await init_db(db)
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in await cursor.fetchall()]
    await db.close()
    assert "agents" in tables
    assert "messages" in tables
    assert "archived_threads" in tables
    assert "trashed_threads" in tables
    assert "trashed_messages" in tables


async def test_init_is_idempotent():
    db = await get_db(":memory:")
    await init_db(db)
    await init_db(db)  # should not raise
    cursor = await db.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='agents'"
    )
    count = (await cursor.fetchone())[0]
    await db.close()
    assert count == 1


# --- Transaction semantics ---


async def test_sqlite_db_transaction_rolls_back_on_error():
    db = await get_db(":memory:")
    await init_db(db)
    await db.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("baseline", "ok", "t0"),
    )
    await db.commit()

    with pytest.raises(RuntimeError):
        async with db_transaction(db):
            await db.execute(
                "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("inside_tx", "should-rollback", "t1"),
            )
            raise RuntimeError("boom")

    cursor = await db.execute("SELECT key FROM system_settings WHERE key = ?", ("inside_tx",))
    row = await cursor.fetchone()
    await db.close()
    assert row is None  # rolled back


async def test_sqlite_db_transaction_commits_on_success():
    db = await get_db(":memory:")
    await init_db(db)
    async with db_transaction(db):
        await db.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("happy_path", "v", "t"),
        )
    cursor = await db.execute("SELECT value FROM system_settings WHERE key = ?", ("happy_path",))
    row = await cursor.fetchone()
    await db.close()
    assert row is not None and row["value"] == "v"


class _FakeAsyncpgTx:
    """Mimics ``asyncpg.Connection.transaction()`` async context manager."""

    def __init__(self, owner):
        self.owner = owner

    async def __aenter__(self):
        self.owner.tx_entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.owner.tx_exited = True
        self.owner.tx_exit_exc_type = exc_type
        return False  # don't suppress


class _FakeAsyncpgConn:
    def __init__(self):
        self.tx_entered = False
        self.tx_exited = False
        self.tx_exit_exc_type = None
        self.executed = []

    def transaction(self):
        return _FakeAsyncpgTx(self)

    async def execute(self, sql, *args):
        self.executed.append(("execute", sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.executed.append(("fetch", sql, args))
        return []


class _FakeAsyncpgPool:
    def __init__(self, conn):
        self._conn = conn
        self.acquire_calls = 0

    def acquire(self):
        outer = self
        outer.acquire_calls += 1
        class _Acq:
            async def __aenter__(self_inner):
                return outer._conn
            async def __aexit__(self_inner, *exc):
                return False
        return _Acq()

    async def close(self):
        return None


async def test_pg_wrapper_transaction_holds_single_connection():
    conn = _FakeAsyncpgConn()
    pool = _FakeAsyncpgPool(conn)
    db = PgConnectionWrapper(pool)

    async with db_transaction(db):
        # Two writes inside the transaction must reuse the same connection.
        await db.execute("INSERT INTO t VALUES (?)", ("a",))
        await db.execute("UPDATE t SET v = ? WHERE id = ?", ("b", 1))

    assert conn.tx_entered is True
    assert conn.tx_exited is True
    assert conn.tx_exit_exc_type is None
    # Pool is acquired once for the whole transaction, not per-execute.
    assert pool.acquire_calls == 1
    assert len(conn.executed) == 2


async def test_pg_wrapper_transaction_propagates_error_for_rollback():
    conn = _FakeAsyncpgConn()
    pool = _FakeAsyncpgPool(conn)
    db = PgConnectionWrapper(pool)

    with pytest.raises(RuntimeError):
        async with db_transaction(db):
            await db.execute("INSERT INTO t VALUES (?)", ("a",))
            raise RuntimeError("fail")

    # Asyncpg's connection.transaction() context exits with exc_type set, which it would use to ROLLBACK.
    assert conn.tx_entered is True
    assert conn.tx_exited is True
    assert conn.tx_exit_exc_type is RuntimeError
