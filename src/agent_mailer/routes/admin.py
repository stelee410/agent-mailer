import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agent_mailer.config import DOMAIN
from agent_mailer.db import INBOX_VISIBILITY_SQL, MESSAGE_ROW_VISIBLE_SQL
from agent_mailer.dependencies import get_current_user
from agent_mailer.routes.agents import _compute_status
from agent_mailer.forward_body import build_forward_body
from fastapi.responses import HTMLResponse
import math
from agent_mailer.db import _get_database_url
from agent_mailer.models import (
    AdminSendRequest,
    AgentResponse,
    SearchResponse,
    SearchResultItem,
    AgentStats,
    AgentUpdateTagsRequest,
    MessageResponse,
    PaginatedInboxResponse,
    ThreadArchiveStatus,
    ThreadOperatorStatus,
    ThreadSummary,
    TrashedMessageDetail,
    TrashedMessageListItem,
    render_body_html,
)

router = APIRouter(prefix="/admin")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _row_to_response(row) -> MessageResponse:
    d = dict(row)
    d["attachments"] = json.loads(d["attachments"])
    d["is_read"] = bool(d["is_read"])
    d["body_html"] = render_body_html(d["body"])
    return MessageResponse(**d)


def _human_operator_id(user_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, user_id))


def _human_operator_address(username: str) -> str:
    return f"human-operator@{username}.{DOMAIN}"


async def _get_user_addresses(db, user_id: str) -> set[str]:
    cursor = await db.execute("SELECT address FROM agents WHERE user_id = ?", (user_id,))
    return {row["address"] for row in await cursor.fetchall()}


async def _verify_thread_ownership(db, thread_id: str, user_id: str):
    user_addresses = await _get_user_addresses(db, user_id)
    cursor = await db.execute(
        "SELECT from_agent, to_agent FROM messages WHERE thread_id = ?", (thread_id,)
    )
    rows = await cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not any(row["from_agent"] in user_addresses or row["to_agent"] in user_addresses for row in rows):
        raise HTTPException(status_code=404, detail="Thread not found")


async def _verify_message_ownership(db, message_id: str, user_id: str) -> dict:
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    user_addresses = await _get_user_addresses(db, user_id)
    if row["from_agent"] not in user_addresses and row["to_agent"] not in user_addresses:
        raise HTTPException(status_code=404, detail="Message not found")
    return dict(row)


async def _clear_trashed_messages_for_thread(db, thread_id: str) -> None:
    await db.execute(
        "DELETE FROM trashed_messages WHERE message_id IN "
        "(SELECT id FROM messages WHERE thread_id = ?)",
        (thread_id,),
    )


async def _purge_thread_messages(db, thread_id: str) -> None:
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


async def _ensure_human_operator(db, user: dict):
    op_id = _human_operator_id(user["id"])
    op_address = _human_operator_address(user["username"])
    # Check if already exists
    cursor = await db.execute("SELECT id FROM agents WHERE id = ? OR address = ?", (op_id, op_address))
    if await cursor.fetchone():
        return op_id, op_address
    await db.execute(
        """INSERT INTO agents (id, name, address, role, description, system_prompt, user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            op_id,
            "Human Operator",
            op_address,
            "operator",
            "Human operator via WebUI",
            "",
            user["id"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()
    return op_id, op_address


def _parse_agent(row) -> dict:
    d = dict(row)
    raw = d.get("tags", "[]")
    d["tags"] = json.loads(raw) if isinstance(raw, str) else raw
    return d


@router.get("/agents", response_model=list[AgentResponse])
async def admin_list_agents(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at", (user["id"],)
    )
    rows = await cursor.fetchall()
    return [AgentResponse(**_parse_agent(row)) for row in rows]


@router.get("/human-operator")
async def get_human_operator(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    op_id, op_address = await _ensure_human_operator(db, user)
    return {"agent_id": op_id, "address": op_address}


@router.get("/messages/thread/{thread_id}", response_model=list[MessageResponse])
async def admin_thread(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    user_addresses = await _get_user_addresses(db, user["id"])
    cursor = await db.execute(
        "SELECT * FROM messages WHERE thread_id = ? "
        "AND id NOT IN (SELECT message_id FROM trashed_messages) "
        "ORDER BY created_at",
        (thread_id,),
    )
    rows = await cursor.fetchall()
    if not any(row["from_agent"] in user_addresses or row["to_agent"] in user_addresses for row in rows):
        raise HTTPException(status_code=404, detail="Thread not found")
    return [_row_to_response(row) for row in rows]


@router.patch("/messages/{message_id}/read", response_model=MessageResponse)
async def admin_mark_read(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
    await db.commit()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    return _row_to_response(await cursor.fetchone())


@router.patch("/messages/{message_id}/unread", response_model=MessageResponse)
async def admin_mark_unread(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.execute("UPDATE messages SET is_read = 0 WHERE id = ?", (message_id,))
    await db.commit()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    return _row_to_response(await cursor.fetchone())


@router.get("/agents/stats", response_model=list[AgentStats])
async def agents_stats(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute("""
        SELECT
            a.id AS agent_id,
            a.name,
            a.address,
            a.role,
            a.tags,
            a.last_seen,
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
        WHERE a.user_id = ?
        ORDER BY a.created_at
    """, (user["id"],))
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        raw = d.pop("tags", "[]")
        d["tags"] = json.loads(raw) if isinstance(raw, str) else raw
        d["status"] = _compute_status(d.get("last_seen"), d.get("role"))
        result.append(AgentStats(**d))
    return result


@router.put("/agents/{agent_id}/tags")
async def update_agent_tags(
    agent_id: str, req: AgentUpdateTagsRequest, request: Request,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    cursor = await db.execute("SELECT id FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"]))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.execute(
        "UPDATE agents SET tags = ? WHERE id = ?",
        (json.dumps(req.tags, ensure_ascii=False), agent_id),
    )
    await db.commit()
    return {"agent_id": agent_id, "tags": req.tags}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"]))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()
    return {"detail": "Agent deleted", "agent_id": agent_id}


def _threads_summary_sql(*, archived: bool, trashed: bool, user_filter: bool = False) -> str:
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

    user_join = ""
    user_where = ""
    if user_filter:
        user_join = ""
        user_where = "AND EXISTS (SELECT 1 FROM agents a WHERE a.user_id = ? AND (a.address = m.from_agent OR a.address = m.to_agent))"

    return f"""
        SELECT
            m.thread_id AS thread_id,
            MAX(m.created_at) AS last_activity,
            COUNT(DISTINCT m.id) AS message_count,
            COUNT(DISTINCT CASE WHEN m.is_read = 0 THEN m.id END) AS unread_count,
            {preview} AS preview_subject,
            {archived_col},
            {trashed_col}
        FROM messages m
        {user_join}
        WHERE {where} {user_where}
        GROUP BY m.thread_id
        ORDER BY last_activity DESC
        """


@router.get("/threads/summary", response_model=list[ThreadSummary])
async def threads_summary(
    request: Request,
    archived: bool = Query(False),
    trashed: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    if archived and trashed:
        raise HTTPException(
            status_code=400,
            detail="Use only one of archived=true or trashed=true.",
        )
    db = request.app.state.db
    sql = _threads_summary_sql(archived=archived, trashed=trashed, user_filter=True)
    cursor = await db.execute(sql, (user["id"],))
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
async def thread_operator_status(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    archived_at = None
    trashed_at = None
    cursor = await db.execute(
        "SELECT archived_at FROM archived_threads WHERE thread_id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    archived = row is not None
    if row:
        archived_at = row["archived_at"]
    cursor = await db.execute(
        "SELECT trashed_at FROM trashed_threads WHERE thread_id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    trashed = row is not None
    if row:
        trashed_at = row["trashed_at"]
    return ThreadOperatorStatus(archived=archived, trashed=trashed, archived_at=archived_at, trashed_at=trashed_at)


@router.get("/threads/{thread_id}/archive", response_model=ThreadArchiveStatus)
async def thread_archive_status(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    cursor = await db.execute(
        "SELECT archived_at FROM archived_threads WHERE thread_id = ?", (thread_id,)
    )
    row = await cursor.fetchone()
    if row:
        return ThreadArchiveStatus(archived=True, archived_at=row["archived_at"])
    return ThreadArchiveStatus(archived=False, archived_at=None)


@router.post("/threads/{thread_id}/archive")
async def archive_thread(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    cursor = await db.execute("SELECT 1 FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Thread is in trash; restore it before archiving.")
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await db.execute(
        "INSERT INTO archived_threads (thread_id, archived_at) VALUES (?, ?)",
        (thread_id, now),
    )
    await db.commit()
    return {"ok": True, "thread_id": thread_id, "archived_at": now}


@router.post("/threads/{thread_id}/unarchive")
async def unarchive_thread(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await db.commit()
    return {"ok": True, "thread_id": thread_id}


@router.post("/threads/{thread_id}/trash")
async def trash_thread(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    cursor = await db.execute("SELECT 1 FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Thread is already in trash")
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM archived_threads WHERE thread_id = ?", (thread_id,))
    await _clear_trashed_messages_for_thread(db, thread_id)
    await db.execute("DELETE FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    await db.execute(
        "INSERT INTO trashed_threads (thread_id, trashed_at) VALUES (?, ?)",
        (thread_id, now),
    )
    await db.commit()
    return {"ok": True, "thread_id": thread_id, "trashed_at": now}


@router.post("/threads/{thread_id}/restore")
async def restore_thread_from_trash(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    cursor = await db.execute("DELETE FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Thread is not in trash")
    await db.commit()
    return {"ok": True, "thread_id": thread_id}


@router.post("/threads/{thread_id}/purge")
async def purge_thread(thread_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_thread_ownership(db, thread_id, user["id"])
    cursor = await db.execute("SELECT 1 FROM trashed_threads WHERE thread_id = ?", (thread_id,))
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


@router.get("/messages/inbox/{address}")
async def admin_inbox(
    address: str, request: Request, all: bool = False,
    page: int | None = Query(default=None, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    # Verify address belongs to current user
    cursor = await db.execute("SELECT user_id FROM agents WHERE address = ?", (address,))
    row = await cursor.fetchone()
    if not row or row["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Address not found")
    vis = INBOX_VISIBILITY_SQL
    where = f"to_agent = ? AND {vis}" if all else f"to_agent = ? AND is_read = 0 AND {vis}"

    if page is not None:
        cursor = await db.execute(f"SELECT COUNT(*) AS cnt FROM messages WHERE {where}", (address,))
        cnt_row = await cursor.fetchone()
        total = cnt_row["cnt"] if cnt_row else 0
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (address, page_size, offset),
        )
        rows = await cursor.fetchall()
        return PaginatedInboxResponse(
            messages=[_row_to_response(row) for row in rows],
            total=total, page=page, page_size=page_size, total_pages=total_pages,
        )
    else:
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
async def admin_send(req: AdminSendRequest, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db

    op_id, op_address = await _ensure_human_operator(db, user)

    recipients = req.to_agent if isinstance(req.to_agent, list) else [req.to_agent]

    for addr in recipients:
        cursor = await db.execute("SELECT user_id FROM agents WHERE address = ?", (addr,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Recipient address '{addr}' not found")
        if row["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail=f"Recipient '{addr}' does not belong to current user")

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
            raise HTTPException(status_code=400, detail="forward_scope is only allowed when action is forward")
        try:
            body_to_store = await build_forward_body(
                db, parent_id=req.parent_id, forward_scope=req.forward_scope, user_body=req.body,
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
            (msg_id, thread_id, op_address, addr, req.action,
             req.subject, body_to_store, "[]", req.parent_id, now),
        )
        results.append(MessageResponse(
            id=msg_id, thread_id=thread_id, from_agent=op_address,
            to_agent=addr, action=req.action, subject=req.subject,
            body=body_to_store, body_html=body_html, attachments=[], is_read=False,
            parent_id=req.parent_id, created_at=now,
        ))
    await db.commit()

    if len(results) == 1:
        return results[0]
    return results


@router.get("/trash/messages", response_model=list[TrashedMessageListItem])
async def list_trashed_messages(request: Request, user: dict = Depends(get_current_user)):
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
        WHERE EXISTS (
            SELECT 1 FROM agents a
            WHERE a.user_id = ? AND (a.address = m.from_agent OR a.address = m.to_agent)
        )
        ORDER BY tm.trashed_at DESC
        """,
        (user["id"],),
    )
    rows = await cursor.fetchall()
    return [TrashedMessageListItem(**dict(row)) for row in rows]


@router.get("/trash/messages/{message_id}", response_model=TrashedMessageDetail)
async def get_trashed_message(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_message_ownership(db, message_id, user["id"])
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
async def trash_single_message(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    msg = await _verify_message_ownership(db, message_id, user["id"])
    thread_id = msg["thread_id"]
    cursor = await db.execute("SELECT 1 FROM trashed_threads WHERE thread_id = ?", (thread_id,))
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400, detail="Thread is in trash; restore the thread or delete it permanently.",
        )
    cursor = await db.execute("SELECT 1 FROM trashed_messages WHERE message_id = ?", (message_id,))
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Message is already in trash")
    cursor = await db.execute("SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1", (message_id,))
    if await cursor.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Cannot trash a message that has replies; trash replies first or trash the whole thread.",
        )
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("INSERT INTO trashed_messages (message_id, trashed_at) VALUES (?, ?)", (message_id, now))
    await db.commit()
    return {"ok": True, "message_id": message_id, "trashed_at": now}


@router.post("/messages/{message_id}/restore")
async def restore_single_message(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_message_ownership(db, message_id, user["id"])
    cursor = await db.execute("DELETE FROM trashed_messages WHERE message_id = ?", (message_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Message is not in trash")
    await db.commit()
    return {"ok": True, "message_id": message_id}


@router.post("/messages/{message_id}/purge")
async def purge_single_message(message_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await _verify_message_ownership(db, message_id, user["id"])
    cursor = await db.execute("SELECT 1 FROM trashed_messages WHERE message_id = ?", (message_id,))
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=400, detail="Message is not in trash; move to trash before permanent delete.",
        )
    cursor = await db.execute("SELECT 1 FROM messages WHERE parent_id = ? LIMIT 1", (message_id,))
    if await cursor.fetchone():
        raise HTTPException(status_code=400, detail="Cannot purge a message that has replies.")
    await db.execute("DELETE FROM trashed_messages WHERE message_id = ?", (message_id,))
    await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    await db.commit()
    return {"ok": True, "message_id": message_id}


@router.get("/search", response_model=SearchResponse)
async def admin_search(
    request: Request, q: str = Query(..., min_length=1),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    is_pg = _get_database_url() is not None
    like_op = "ILIKE" if is_pg else "LIKE"
    pattern = f"%{q}%"

    where = f"""
        (m.subject {like_op} ? OR m.body {like_op} ?)
        AND EXISTS (SELECT 1 FROM agents a WHERE a.user_id = ? AND (a.address = m.from_agent OR a.address = m.to_agent))
    """
    params = (pattern, pattern, user["id"])

    cursor = await db.execute(f"SELECT COUNT(*) AS cnt FROM messages m WHERE {where}", params)
    cnt_row = await cursor.fetchone()
    total = cnt_row["cnt"] if cnt_row else 0
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size

    cursor = await db.execute(
        f"SELECT m.id, m.thread_id, m.subject, m.body, m.from_agent, m.to_agent, m.created_at FROM messages m WHERE {where} ORDER BY m.created_at DESC LIMIT ? OFFSET ?",
        (*params, page_size, offset),
    )
    rows = await cursor.fetchall()

    def snippet(body, query, length=100):
        lower_body = body.lower()
        idx = lower_body.find(query.lower())
        if idx == -1:
            return body[:200] if len(body) > 200 else body
        start = max(0, idx - length)
        end = min(len(body), idx + len(query) + length)
        s = body[start:end]
        if start > 0:
            s = "..." + s
        if end < len(body):
            s = s + "..."
        return s

    results = []
    for row in rows:
        d = dict(row)
        results.append(SearchResultItem(
            message_id=d["id"],
            thread_id=d["thread_id"],
            subject=d["subject"],
            body_snippet=snippet(d["body"], q),
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            created_at=d["created_at"],
        ))

    return SearchResponse(
        messages=results, total=total, page=page,
        page_size=page_size, total_pages=total_pages, query=q,
    )


@router.get("/ui", response_class=HTMLResponse)
async def ui():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
