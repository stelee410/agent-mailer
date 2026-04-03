import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from agent_mailer.db import INBOX_VISIBILITY_SQL
from agent_mailer.forward_body import build_forward_body
from agent_mailer.models import SendRequest, MessageResponse, render_body_html

router = APIRouter()


def _row_to_response(row) -> MessageResponse:
    d = dict(row)
    d["attachments"] = json.loads(d["attachments"])
    d["is_read"] = bool(d["is_read"])
    d["body_html"] = render_body_html(d["body"])
    return MessageResponse(**d)


async def _verify_identity(db, agent_id: str, address: str):
    """Verify that agent_id exists and its address matches the given address."""
    cursor = await db.execute("SELECT address FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if row["address"] != address:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' does not own address '{address}'",
        )


@router.post("/messages/send", response_model=MessageResponse | list[MessageResponse])
async def send_message(req: SendRequest, request: Request):
    db = request.app.state.db

    # verify sender identity: agent_id must own from_agent address
    await _verify_identity(db, req.agent_id, req.from_agent)

    # normalize to_agent to list
    recipients = req.to_agent if isinstance(req.to_agent, list) else [req.to_agent]

    # validate all recipient addresses exist
    for addr in recipients:
        cursor = await db.execute("SELECT id FROM agents WHERE address = ?", (addr,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Recipient address '{addr}' not found")

    # reply/forward require parent_id
    if req.action in ("reply", "forward") and not req.parent_id:
        raise HTTPException(status_code=400, detail="parent_id is required for reply/forward")

    # resolve thread_id
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
    attachments_json = json.dumps(req.attachments)
    body_html = render_body_html(body_to_store)

    results = []
    for addr in recipients:
        msg_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO messages (id, thread_id, from_agent, to_agent, action, subject, body, attachments, is_read, parent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (msg_id, thread_id, req.from_agent, addr, req.action,
             req.subject, body_to_store, attachments_json, req.parent_id, now),
        )
        results.append(MessageResponse(
            id=msg_id, thread_id=thread_id, from_agent=req.from_agent,
            to_agent=addr, action=req.action, subject=req.subject,
            body=body_to_store, body_html=body_html, attachments=req.attachments,
            is_read=False, parent_id=req.parent_id, created_at=now,
        ))
    await db.commit()

    # backward compatible: return single object for single recipient
    if len(results) == 1:
        return results[0]
    return results


@router.get("/messages/inbox/{address}", response_model=list[MessageResponse])
async def inbox(address: str, request: Request, agent_id: str = Query(...), all: bool = False):
    db = request.app.state.db

    # verify caller identity: agent_id must own this address
    await _verify_identity(db, agent_id, address)

    vis = INBOX_VISIBILITY_SQL
    if all:
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE to_agent = ? AND {vis} ORDER BY created_at",
            (address,),
        )
    else:
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE to_agent = ? AND is_read = 0 AND {vis} ORDER BY created_at",
            (address,),
        )
    rows = await cursor.fetchall()
    return [_row_to_response(row) for row in rows]


@router.get("/messages/thread/{thread_id}", response_model=list[MessageResponse])
async def thread(thread_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM messages WHERE thread_id = ? "
        "AND id NOT IN (SELECT message_id FROM trashed_messages) "
        "ORDER BY created_at",
        (thread_id,),
    )
    rows = await cursor.fetchall()
    return [_row_to_response(row) for row in rows]


@router.patch("/messages/{message_id}/read", response_model=MessageResponse)
async def mark_read(message_id: str, request: Request):
    db = request.app.state.db
    await db.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
    await db.commit()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return _row_to_response(row)
