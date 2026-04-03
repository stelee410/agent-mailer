"""Build forward message bodies from the parent message or full thread."""

from __future__ import annotations

import aiosqlite


def _format_message_block(m: dict) -> str:
    lines = [
        f"From: {m['from_agent']} → To: {m['to_agent']}",
        f"Time: {m['created_at']}",
        f"Action: {m['action']}",
    ]
    subj = (m.get("subject") or "").strip()
    if subj:
        lines.append(f"Subject: {subj}")
    lines.append("")
    lines.append(m.get("body") or "")
    return "\n".join(lines)


async def build_forward_body(
    db: aiosqlite.Connection,
    *,
    parent_id: str,
    forward_scope: str,
    user_body: str,
) -> str:
    """Combine optional user note with quoted message(s). *forward_scope* is ``message`` or ``thread``."""
    note = (user_body or "").strip()
    if forward_scope == "message":
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (parent_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError("Parent message not found")
        block = _format_message_block(dict(row))
    elif forward_scope == "thread":
        cursor = await db.execute(
            "SELECT thread_id FROM messages WHERE id = ?",
            (parent_id,),
        )
        r = await cursor.fetchone()
        if not r:
            raise ValueError("Parent message not found")
        tid = r["thread_id"]
        cursor = await db.execute(
            "SELECT * FROM messages WHERE thread_id = ? "
            "AND id NOT IN (SELECT message_id FROM trashed_messages) "
            "ORDER BY created_at",
            (tid,),
        )
        rows = await cursor.fetchall()
        parts = [_format_message_block(dict(x)) for x in rows]
        block = "\n\n---\n\n".join(parts)
    else:
        raise ValueError(f"Invalid forward_scope: {forward_scope!r}")

    if note:
        return f"{note}\n\n----------\n\n{block}"
    return block
