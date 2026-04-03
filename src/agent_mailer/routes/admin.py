import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from agent_mailer.models import (
    AdminSendRequest,
    AgentStats,
    MessageResponse,
    ThreadArchiveStatus,
    ThreadSummary,
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


def _threads_summary_sql(archived: bool) -> str:
    where = (
        "m.thread_id IN (SELECT thread_id FROM archived_threads)"
        if archived
        else "m.thread_id NOT IN (SELECT thread_id FROM archived_threads)"
    )
    archived_col = (
        "(SELECT a.archived_at FROM archived_threads a WHERE a.thread_id = m.thread_id LIMIT 1) AS archived_at"
        if archived
        else "NULL AS archived_at"
    )
    return f"""
        SELECT
            m.thread_id AS thread_id,
            MAX(m.created_at) AS last_activity,
            COUNT(*) AS message_count,
            SUM(CASE WHEN m.is_read = 0 THEN 1 ELSE 0 END) AS unread_count,
            (
                SELECT m2.subject
                FROM messages m2
                WHERE m2.thread_id = m.thread_id
                ORDER BY m2.created_at ASC
                LIMIT 1
            ) AS preview_subject,
            {archived_col}
        FROM messages m
        WHERE {where}
        GROUP BY m.thread_id
        ORDER BY last_activity DESC
        """


@router.get("/threads/summary", response_model=list[ThreadSummary])
async def threads_summary(
    request: Request,
    archived: bool = Query(False, description="If true, list archived threads only; default lists active threads."),
):
    """List message threads for the operator console (newest activity first)."""
    db = request.app.state.db
    cursor = await db.execute(_threads_summary_sql(archived))
    rows = await cursor.fetchall()
    return [
        ThreadSummary(
            thread_id=row["thread_id"],
            last_activity=row["last_activity"],
            message_count=int(row["message_count"]),
            unread_count=int(row["unread_count"]),
            preview_subject=row["preview_subject"] or "",
            archived_at=row["archived_at"],
        )
        for row in rows
    ]


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


@router.get("/messages/inbox/{address}", response_model=list[MessageResponse])
async def admin_inbox(address: str, request: Request, all: bool = False):
    """Peek at any agent's inbox without identity verification."""
    db = request.app.state.db
    if all:
        cursor = await db.execute(
            "SELECT * FROM messages WHERE to_agent = ? ORDER BY created_at DESC",
            (address,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM messages WHERE to_agent = ? AND is_read = 0 ORDER BY created_at DESC",
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

    now = datetime.now(timezone.utc).isoformat()
    body_html = render_body_html(req.body)

    results = []
    for addr in recipients:
        msg_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, attachments, is_read, parent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (msg_id, thread_id, HUMAN_OPERATOR_ADDRESS, addr, req.action,
             req.subject, req.body, "[]", req.parent_id, now),
        )
        results.append(MessageResponse(
            id=msg_id, thread_id=thread_id, from_agent=HUMAN_OPERATOR_ADDRESS,
            to_agent=addr, action=req.action, subject=req.subject,
            body=req.body, body_html=body_html, attachments=[], is_read=False,
            parent_id=req.parent_id, created_at=now,
        ))
    await db.commit()

    if len(results) == 1:
        return results[0]
    return results


@router.get("/ui", response_class=HTMLResponse)
async def ui():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
