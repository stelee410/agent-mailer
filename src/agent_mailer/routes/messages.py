import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agent_mailer.db import INBOX_VISIBILITY_SQL
from agent_mailer.dependencies import get_api_key_user
from agent_mailer.forward_body import build_forward_body
from agent_mailer.models import SendRequest, MessageResponse, PaginatedInboxResponse, render_body_html
import math

router = APIRouter()


def _row_to_response(row) -> MessageResponse:
    d = dict(row)
    d["attachments"] = json.loads(d["attachments"])
    d["is_read"] = bool(d["is_read"])
    d["body_html"] = render_body_html(d["body"])
    return MessageResponse(**d)


async def _verify_identity(db, agent_id: str, address: str, user_id: str):
    """Verify that agent_id exists, its address matches, and it belongs to user."""
    cursor = await db.execute(
        "SELECT address, user_id FROM agents WHERE id = ?", (agent_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if row["address"] != address:
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_id}' does not own address '{address}'",
        )
    if row["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail="Agent does not belong to current user",
        )


async def _verify_address_ownership(db, address: str, user_id: str):
    """Verify that the given address belongs to an agent owned by user_id."""
    cursor = await db.execute(
        "SELECT user_id FROM agents WHERE address = ?", (address,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Address '{address}' not found")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Address does not belong to current user")


@router.post("/messages/send", response_model=MessageResponse | list[MessageResponse])
async def send_message(
    req: SendRequest, request: Request, user: dict = Depends(get_api_key_user)
):
    db = request.app.state.db

    # verify sender identity: agent_id must own from_agent address and belong to user
    await _verify_identity(db, req.agent_id, req.from_agent, user["id"])

    # normalize to_agent to list
    recipients = req.to_agent if isinstance(req.to_agent, list) else [req.to_agent]

    # validate all recipient addresses exist and belong to same user (no cross-tenant)
    for addr in recipients:
        cursor = await db.execute("SELECT user_id FROM agents WHERE address = ?", (addr,))
        recipient_row = await cursor.fetchone()
        if not recipient_row:
            raise HTTPException(status_code=404, detail=f"Recipient address '{addr}' not found")
        if recipient_row["user_id"] != user["id"]:
            raise HTTPException(
                status_code=403,
                detail=f"Cross-tenant messaging is not allowed (recipient '{addr}')",
            )

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


@router.get("/messages/inbox/{address}")
async def inbox(
    address: str, request: Request, agent_id: str = Query(...),
    all: bool = False, page: int | None = None, page_size: int = 20,
    user: dict = Depends(get_api_key_user),
):
    db = request.app.state.db

    # verify caller identity: agent_id must own this address and belong to user
    await _verify_identity(db, agent_id, address, user["id"])

    # update last_seen heartbeat (best-effort, don't break inbox if column missing)
    try:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute("UPDATE agents SET last_seen = ? WHERE id = ?", (now, agent_id))
        await db.commit()
    except Exception:
        pass

    vis = INBOX_VISIBILITY_SQL
    where = f"to_agent = ? AND {vis}" if all else f"to_agent = ? AND is_read = 0 AND {vis}"

    if page is not None:
        # Paginated response
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
        # Backward compatible: return list
        cursor = await db.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at", (address,),
        )
        rows = await cursor.fetchall()
        return [_row_to_response(row) for row in rows]


@router.get("/messages/thread/{thread_id}", response_model=list[MessageResponse])
async def thread(
    thread_id: str, request: Request, user: dict = Depends(get_api_key_user)
):
    db = request.app.state.db

    # Get all user's agent addresses
    cursor = await db.execute(
        "SELECT address FROM agents WHERE user_id = ?", (user["id"],)
    )
    user_addresses = {row["address"] for row in await cursor.fetchall()}

    cursor = await db.execute(
        "SELECT * FROM messages WHERE thread_id = ? "
        "AND id NOT IN (SELECT message_id FROM trashed_messages) "
        "ORDER BY created_at",
        (thread_id,),
    )
    rows = await cursor.fetchall()

    # Verify at least one message involves current user's agent
    if not any(row["from_agent"] in user_addresses or row["to_agent"] in user_addresses for row in rows):
        raise HTTPException(status_code=404, detail="Thread not found")

    return [_row_to_response(row) for row in rows]


@router.patch("/messages/{message_id}/read", response_model=MessageResponse)
async def mark_read(
    message_id: str, request: Request, user: dict = Depends(get_api_key_user)
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")

    # Verify to_agent belongs to current user
    await _verify_address_ownership(db, row["to_agent"], user["id"])

    await db.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
    await db.commit()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    return _row_to_response(row)


@router.patch("/messages/{message_id}/unread", response_model=MessageResponse)
async def mark_unread(
    message_id: str, request: Request, user: dict = Depends(get_api_key_user)
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")

    # Verify to_agent belongs to current user
    await _verify_address_ownership(db, row["to_agent"], user["id"])

    await db.execute("UPDATE messages SET is_read = 0 WHERE id = ?", (message_id,))
    await db.commit()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = await cursor.fetchone()
    return _row_to_response(row)
