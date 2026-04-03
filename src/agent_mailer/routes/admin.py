import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from agent_mailer.db import INBOX_VISIBILITY_SQL, MESSAGE_ROW_VISIBLE_SQL
from agent_mailer.forward_body import build_forward_body
from fastapi.responses import HTMLResponse
from agent_mailer.models import (
    AdminSendRequest,
    AgentStats,
    MessageResponse,
    ThreadArchiveStatus,
    ThreadOperatorStatus,
    ThreadSummary,
    TrashedMessageDetail,
    TrashedMessageListItem,
    render_body_html,
)

router = APIRouter(prefix="/admin")

HUMAN_OPERATOR_ID = "00000000-0000-0000-0000-000000000000"
HUMAN_OPERATOR_ADDRESS = "human-operator@local"

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _row_to_response(row) -> MessageResponse:
    d = dict(row)
    d["attachments"] = json.loads(d["attachments"])
    d["is_read"] = bool(d["is_read"])
    d["body_html"] = render_body_html(d["body"])
    return MessageResponse(**d)


async def _clear_trashed_messages_for_thread(db, thread_id: str) -> None:
    await db.execute(
        "DELETE FROM trashed_messages WHERE message_id IN "
        "(SELECT id FROM messages WHERE thread_id = ?)",
        (thread_id,),
    )


async def _purge_thread_messages(db, thread_id: str) -> None:
    """Delete all messages in a thread (respects parent_id FK order)."""
    while True:
        cursor = await db.execute(
            """
            DELETE FROM messages
            WHERE thread_id = ?
              AND id NOT IN (
                SELECT parent_id FROM messages
                WHERE parent_id IS NOT NULL AND thread_id = ?
              )
            """,
            (thread_id, thread_id),
        )
        if cursor.rowcount == 0:
            break


async def _ensure_human_operator(db):
    """Lazily register the human-operator agent if it doesn't exist."""
    await db.execute(
        """INSERT OR IGNORE INTO agents (id, name, address, role, description, system_prompt, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            HUMAN_OPERATOR_ID,
            "Human Operator",
            HUMAN_OPERATOR_ADDRESS,
            "operator",
            "Human operator via WebUI",
            "",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()


@router.get("/agents/stats", response_model=list[AgentStats])
async def agents_stats(request: Request):
    db = request.app.state.db
    cursor = await db.execute("""
        SELECT
            a.id AS agent_id,
            a.name,
            a.address,
            a.role,
            COALESCE(recv.total, 0) AS messages_received,
            COALESCE(recv.read_count, 0) AS messages_read,
            COALESCE(recv.total, 0) - COALESCE(recv.read_count, 0) AS messages_unread,
            COALESCE(sent.total, 0) AS messages_sent,
            COALESCE(sent.reply_count, 0) AS messages_replied,
            COALESCE(sent.forward_count, 0) AS messages_forwarded
        FROM agents a
        LEFT JOIN (
            SELECT to_agent,
                   COUNT(*) AS total,
                   SUM(CASE WHEN is_read = 1 THEN 1 ELSE 0 END) AS read_count
            FROM messages GROUP BY to_agent
        ) recv ON recv.to_agent = a.address
        LEFT JOIN (
            SELECT from_agent,
                   COUNT(*) AS total,
                   SUM(CASE WHEN action = 'reply' THEN 1 ELSE 0 END) AS reply_count,
                   SUM(CASE WHEN action = 'forward' THEN 1 ELSE 0 END) AS forward_count
            FROM messages GROUP BY from_agent
        ) sent ON sent.from_agent = a.address
        ORDER BY a.created_at
    """)
    rows = await cursor.fetchall()
    return [AgentStats(**dict(row)) for row in rows]


def _threads_summary_sql(*, archived: bool, trashed: bool) -> str:
    mv = MESSAGE_ROW_VISIBLE_SQL
    if trashed:
        where = "m.thread_id IN (SELECT thread_id FROM trashed_threads)"
        preview = """
            (
                SELECT m2.subject
                FROM messages m2
                WHERE m2.thread_id = m.thread_id
                ORDER BY m2.created_at ASC
                LIMIT 1
            )
        """
        archived_col = "NULL AS archived_at"
        trashed_col = (
            "(SELECT t.trashed_at FROM trashed_threads t WHERE t.thread_id = m.thread_id LIMIT 1) AS trashed_at"
        )
    elif archived:
        where = (
            f"(m.thread_id IN (SELECT thread_id FROM archived_threads) "
            f"AND m.thread_id NOT IN (SELECT thread_id FROM trashed_threads)) AND ({mv})"
        )
        preview = f"""
            (
                SELECT m2.subject
                FROM messages m2
                WHERE m2.thread_id = m.thread_id
                  AND m2.id NOT IN (SELECT message_id FROM trashed_messages)
                ORDER BY m2.created_at ASC
                LIMIT 1
            )
        """
        archived_col = (
            "(SELECT a.archived_at FROM archived_threads a WHERE a.thread_id = m.thread_id LIMIT 1) AS archived_at"
        )
        trashed_col = "NULL AS trashed_at"
    else:
        where = (
            f"(m.thread_id NOT IN (SELECT thread_id FROM archived_threads) "
            f"AND m.thread_id NOT IN (SELECT thread_id FROM trashed_threads)) AND ({mv})"
        )
        preview = f"""
            (
                SELECT m2.subject
                FROM messages m2
                WHERE m2.thread_id = m.thread_id
                  AND m2.id NOT IN (SELECT message_id FROM trashed_messages)
                ORDER BY m2.created_at ASC
                LIMIT 1
            )
        """
        archived_col = "NULL AS archived_at"
        trashed_col = "NULL AS trashed_at"
    return f"""
        SELECT
            m.thread_id AS thread_id,
            MAX(m.created_at) AS last_activity,
            COUNT(*) AS message_count,
            SUM(CASE WHEN m.is_read = 0 THEN 1 ELSE 0 END) AS unread_count,
            {preview} AS preview_subject,
            {archived_col},
            {trashed_col}
        FROM messages m
        WHERE {where}
        GROUP BY m.thread_id
        ORDER BY last_activity DESC
        """


@router.get("/threads/summary", response_model=list[ThreadSummary])
async def threads_summary(
    request: Request,
    archived: bool = Query(False, description="List archived threads only (excludes trash)."),
    trashed: bool = Query(False, description="List threads in trash only."),
):
    """List message threads for the operator console (newest activity first)."""
    if archived and trashed:
        raise HTTPException(
            status_code=400,
            detail="Use only one of archived=true or trashed=true.",
        )
    db = request.app.state.db
    cursor = await db.execute(_threads_summary_sql(archived=archived, trashed=trashed))
    rows = await cursor.fetchall()
    return [
        ThreadSummary(
            thread_id=row["thread_id"],
            last_activity=row["last_activity"],
            message_count=int(row["message_count"]),
            unread_count=int(row["unread_count"]),
            preview_subject=row["preview_subject"] or "",
            archived_at=row["archived_at"],
            trashed_at=row["trashed_at"],
        )
        for row in rows
    ]


@router.get("/threads/{thread_id}/status", response_model=ThreadOperatorStatus)
async def thread_operator_status(thread_id: str, request: Request):
    db = request.app.state.db
    archived_at = None
    trashed_at = None
    cursor = await db.execute(
        "SELECT archived_at FROM archived_threads WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    archived = row is not None
    if row:
        archived_at = row["archived_at"]
    cursor = await db.execute(
        "SELECT trashed_at FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    trashed = row is not None
    if row:
        trashed_at = row["trashed_at"]
    return ThreadOperatorStatus(
        archived=archived,
        trashed=trashed,
        archived_at=archived_at,
        trashed_at=trashed_at,
    )


@router.get("/threads/{thread_id}/archive", response_model=ThreadArchiveStatus)
async def thread_archive_status(thread_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT archived_at FROM archived_threads WHERE thread_id = ?",
        (thread_id,),
    )
    row = await cursor.fetchone()
    if row:
        return ThreadArchiveStatus(archived=True, archived_at=row["archived_at"])
    return ThreadArchiveStatus(archived=False, archived_at=None)


@router.post("/threads/{thread_id}/archive")
async def archive_thread(thread_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT 1 FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Thread is in trash; restore it before archiving.",
        )
    cursor = await db.execute(
        "SELECT 1 FROM messages WHERE thread_id = ? LIMIT 1",
        (thread_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Thread not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT OR REPLACE INTO archived_threads (thread_id, archived_at) VALUES (?, ?)",
        (thread_id, now),
    )
    await db.commit()
    return {"ok": True, "thread_id": thread_id, "archived_at": now}


@router.post("/threads/{thread_id}/unarchive")
async def unarchive_thread(thread_id: str, request: Request):
    db = request.app.state.db
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await db.commit()
    return {"ok": True, "thread_id": thread_id}


@router.post("/threads/{thread_id}/trash")
async def trash_thread(thread_id: str, request: Request):
    """Soft-delete: move thread to trash (removes archive flag). Messages kept until purge."""
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT 1 FROM messages WHERE thread_id = ? LIMIT 1",
        (thread_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Thread not found")
    cursor = await db.execute(
        "SELECT 1 FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Thread is already in trash")
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await _clear_trashed_messages_for_thread(db, thread_id)
    await db.execute(
        "INSERT OR REPLACE INTO trashed_threads (thread_id, trashed_at) VALUES (?, ?)",
        (thread_id, now),
    )
    await db.commit()
    return {"ok": True, "thread_id": thread_id, "trashed_at": now}


@router.post("/threads/{thread_id}/restore")
async def restore_thread_from_trash(thread_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        "DELETE FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Thread is not in trash")
    await db.commit()
    return {"ok": True, "thread_id": thread_id}


@router.post("/threads/{thread_id}/purge")
async def purge_thread(thread_id: str, request: Request):
    """Permanently delete all messages for a thread (must be in trash)."""
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT 1 FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Thread is not in trash; move to trash before permanent delete.",
        )
    await _clear_trashed_messages_for_thread(db, thread_id)
    await _purge_thread_messages(db, thread_id)
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await db.execute("DELETE FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    await db.commit()
    return {"ok": True, "thread_id": thread_id}


@router.get("/messages/inbox/{address}", response_model=list[MessageResponse])
async def admin_inbox(address: str, request: Request, all: bool = False):
    """Peek at any agent's inbox without identity verification."""
    db = request.app.state.db
    vis = INBOX_VISIBILITY_SQL
    if all:
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE to_agent = ? AND {vis} ORDER BY created_at DESC",
            (address,),
        )
    else:
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE to_agent = ? AND is_read = 0 AND {vis} ORDER BY created_at DESC",
            (address,),
        )
    rows = await cursor.fetchall()
    return [_row_to_response(row) for row in rows]


@router.post("/messages/send", response_model=MessageResponse | list[MessageResponse])
async def admin_send(req: AdminSendRequest, request: Request):
    """Send a message as the human operator."""
    db = request.app.state.db

    await _ensure_human_operator(db)

    # normalize to_agent to list
    recipients = req.to_agent if isinstance(req.to_agent, list) else [req.to_agent]

    # validate all recipient addresses exist
    for addr in recipients:
        cursor = await db.execute("SELECT id FROM agents WHERE address = ?", (addr,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Recipient address '{addr}' not found")

    if req.action in ("reply", "forward") and not req.parent_id:
        raise HTTPException(status_code=400, detail="parent_id is required for reply/forward")

    if req.action == "send":
        thread_id = str(uuid.uuid4())
    else:
        cursor = await db.execute("SELECT thread_id FROM messages WHERE id = ?", (req.parent_id,))
        parent = await cursor.fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent message not found")
        thread_id = parent["thread_id"]

    body_to_store = req.body
    if req.forward_scope is not None:
        if req.action != "forward":
            raise HTTPException(
                status_code=400,
                detail="forward_scope is only allowed when action is forward",
            )
        try:
            body_to_store = await build_forward_body(
                db,
                parent_id=req.parent_id,
                forward_scope=req.forward_scope,
                user_body=req.body,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    now = datetime.now(timezone.utc).isoformat()
    body_html = render_body_html(body_to_store)

    results = []
    for addr in recipients:
        msg_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, attachments, is_read, parent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (msg_id, thread_id, HUMAN_OPERATOR_ADDRESS, addr, req.action,
             req.subject, body_to_store, "[]", req.parent_id, now),
        )
        results.append(MessageResponse(
            id=msg_id, thread_id=thread_id, from_agent=HUMAN_OPERATOR_ADDRESS,
            to_agent=addr, action=req.action, subject=req.subject,
            body=body_to_store, body_html=body_html, attachments=[], is_read=False,
            parent_id=req.parent_id, created_at=now,
        ))
    await db.commit()

    if len(results) == 1:
        return results[0]
    return results


@router.get("/trash/messages", response_model=list[TrashedMessageListItem])
async def list_trashed_messages(request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        """
        SELECT
            m.id AS message_id,
            m.thread_id AS thread_id,
            tm.trashed_at AS trashed_at,
            m.from_agent AS from_agent,
            m.to_agent AS to_agent,
            m.action AS action,
            m.subject AS subject,
            m.created_at AS created_at
        FROM trashed_messages tm
        INNER JOIN messages m ON m.id = tm.message_id
        ORDER BY tm.trashed_at DESC
        """
    )
    rows = await cursor.fetchall()
    return [TrashedMessageListItem(**dict(row)) for row in rows]


@router.get("/trash/messages/{message_id}", response_model=TrashedMessageDetail)
async def get_trashed_message(message_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        """
        SELECT tm.trashed_at AS trashed_at, m.*
        FROM trashed_messages tm
        INNER JOIN messages m ON m.id = tm.message_id
        WHERE tm.message_id = ?
        """,
        (message_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message is not in trash")
    d = dict(row)
    trashed_at = d.pop("trashed_at")
    msg = _row_to_response(d)
    return TrashedMessageDetail(trashed_at=trashed_at, message=msg)


@router.post("/messages/{message_id}/trash")
async def trash_single_message(message_id: str, request: Request):
    """Move one message to trash (no replies may reference it). Thread cannot be in thread-trash."""
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT thread_id FROM messages WHERE id = ?",
        (message_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    thread_id = row["thread_id"]
    cursor = await db.execute(
        "SELECT 1 FROM trashed_threads WHERE thread_id = ?",
        (thread_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Thread is in trash; restore the thread or delete it permanently.",
        )
    cursor = await db.execute(
        "SELECT 1 FROM trashed_messages WHERE message_id = ?",
        (message_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Message is already in trash")
    cursor = await db.execute(
        "SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1",
        (message_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Cannot trash a message that has replies; trash replies first or trash the whole thread.",
        )
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO trashed_messages (message_id, trashed_at) VALUES (?, ?)",
        (message_id, now),
    )
    await db.commit()
    return {"ok": True, "message_id": message_id, "trashed_at": now}


@router.post("/messages/{message_id}/restore")
async def restore_single_message(message_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        "DELETE FROM trashed_messages WHERE message_id = ?",
        (message_id,),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Message is not in trash")
    await db.commit()
    return {"ok": True, "message_id": message_id}


@router.post("/messages/{message_id}/purge")
async def purge_single_message(message_id: str, request: Request):
    """Permanently delete one message (must be in message-trash, no replies)."""
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT 1 FROM trashed_messages WHERE message_id = ?",
        (message_id,),
    )
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Message is not in trash; move to trash before permanent delete.",
        )
    cursor = await db.execute(
        "SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1",
        (message_id,),
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Cannot purge a message that has replies.",
        )
    await db.execute("DELETE FROM trashed_messages WHERE message_id = ?", (message_id,))
    await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    await db.commit()
    return {"ok": True, "message_id": message_id}


@router.get("/ui", response_class=HTMLResponse)
async def ui():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
