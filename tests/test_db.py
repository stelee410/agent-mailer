from agent_mailer.db import init_db, get_db


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
