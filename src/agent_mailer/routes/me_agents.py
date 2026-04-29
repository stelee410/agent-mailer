"""Self-service agent management at ``/users/me/agents/*``.

Each authenticated user gets a parallel CRUD surface scoped to agents
they personally own (``agents.user_id == current_user.id``). The
superadmin-only ``/superadmin/agents/*`` namespace remains untouched —
admins keep their global view of every agent. Permission checks happen
in *every* handler; passing someone else's agent id returns 404 (we
deliberately don't leak existence with a 403).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agent_mailer.auth import generate_api_key
from agent_mailer.config import DOMAIN
from agent_mailer.db import db_transaction
from agent_mailer.dependencies import get_current_user
from agent_mailer.models import (
    UserAgentCreateRequest,
    UserAgentCreateResponse,
    UserAgentExportResponse,
    UserAgentRegenerateKeyResponse,
    UserAgentResponse,
    UserAgentUpdateRequest,
)
from agent_mailer.utils import get_base_url

router = APIRouter(prefix="/users/me/agents", tags=["me-agents"])

# Reuse the same local-part rules the admin namespace settled on (P3-3 in 1f7c683):
# alphanumeric on both ends, length 1-63, dashes/dots/underscores allowed in the middle.
_ADDRESS_LOCAL_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,61}[a-z0-9])?$")


def _user_domain_suffix(username: str) -> str:
    return f"@{username}.{DOMAIN}"


def _mask_api_key(suffix: str) -> str:
    return f"amk_****{suffix}" if suffix else "amk_****"


def _parse_agent_row(row) -> dict:
    d = dict(row)
    raw = d.get("tags", "[]")
    d["tags"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return d


def _agent_to_response(row) -> UserAgentResponse:
    d = _parse_agent_row(row)
    return UserAgentResponse(
        id=d["id"],
        name=d["name"],
        address=d["address"],
        role=d.get("role", "") or "",
        description=d.get("description", "") or "",
        system_prompt=d.get("system_prompt", "") or "",
        tags=d.get("tags", []),
        team_id=d.get("team_id"),
        status=d.get("status") or "active",
        created_at=d["created_at"],
        last_seen=d.get("last_seen"),
        api_key_masked=_mask_api_key(d.get("api_key_suffix") or ""),
    )


async def _validate_team_ownership(db, team_id: str | None, user_id: str) -> None:
    """Reject a team_id that doesn't belong to the current user.

    A NULL team_id ("ungrouped") is always allowed. This is enforced
    server-side because the frontend dropdown is *advisory*; a forged
    request must still 400.
    """
    if not team_id:
        return
    cursor = await db.execute(
        "SELECT id FROM teams WHERE id = ? AND user_id = ?", (team_id, user_id)
    )
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=400, detail="team_id must belong to one of your teams"
        )


def _build_user_agent_md(agent_row, broker_url: str, namespace_suffix: str) -> str:
    """Render AGENT.md / SOUL.md for a self-service user-owned agent.

    Mirrors the admin-namespace template but the security note speaks of
    the per-user namespace and uses ``<your_api_key>`` as a placeholder
    (the frontend substitutes the real plaintext when it has just been
    issued). Kept intentionally close in shape to its sibling in
    ``superadmin.py`` so both exports read alike for downstream agents.
    """
    name = agent_row["name"]
    role = agent_row["role"] or ""
    address = agent_row["address"]
    agent_id = agent_row["id"]
    system_prompt = agent_row["system_prompt"] or ""
    key = "<your_api_key>"

    return f"""# Agent Identity

- **Name**: {name}
- **Role**: {role}
- **Address**: {address}
- **Agent ID**: {agent_id}
- **Broker URL**: {broker_url}

## ⚠️ Security Note / 安全须知

All agents owned by the same account share authentication scope. Any
agent holding a valid X-API-Key for `{namespace_suffix}` can
theoretically access another of *your* agents' mailboxes by passing
that target's `agent_id` and `address`. This is by design (single-owner
trust model). **Do NOT distribute this API key beyond the trusted
operators of this account.**

同一账户下的所有 Agent 共享同一鉴权作用域。持有任意一把
`{namespace_suffix}` 命名空间下有效 X-API-Key 的 Agent，理论上可通过
传入目标 `agent_id` 与 `address` 读写同账户内其他 Agent 的邮箱。这是
设计如此（单账户信任模型）。**严禁将此 API Key 分发给账户运维之外
的成员。**

## 身份提示词 (System Prompt)

{system_prompt}

## 邮箱协议

你是多智能体协作网络中的一个节点。你通过 Mail Broker 与其他 Agent 异步通信。
你的邮箱地址是 `{address}`，所有收发件均使用此地址。

### 认证
所有 API 请求必须携带 `X-API-Key` 头：
```
X-API-Key: {key}
```

### 收件 (读取任务)
```
GET {broker_url}/messages/inbox/{address}?agent_id={agent_id}
Headers: X-API-Key: {key}
```

### 发件 (发送消息)
```
POST {broker_url}/messages/send
Headers: X-API-Key: {key}
Body: {{"agent_id": "{agent_id}", "from_agent": "{address}", "to_agent": "<目标agent地址>", "action": "send|reply|forward", "subject": "...", "body": "...", "parent_id": "<reply/forward 时必填>", "forward_scope": "<可选，仅 forward：message=仅父邮件 | thread=整线（不含已删单封）>"}}
```

### 标记已读
```
PATCH {broker_url}/messages/{{message_id}}/read
PATCH {broker_url}/messages/{{message_id}}/unread
Headers: X-API-Key: {key}
```

### 查看会话线程
```
GET {broker_url}/messages/thread/{{thread_id}}
Headers: X-API-Key: {key}
```

### 查看所有 Agent
```
GET {broker_url}/agents
Headers: X-API-Key: {key}
```
"""


@router.get("", response_model=list[UserAgentResponse])
async def list_my_agents(
    request: Request,
    include_deleted: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    if include_deleted:
        sql = "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at DESC"
    else:
        sql = "SELECT * FROM agents WHERE user_id = ? AND status != 'deleted' ORDER BY created_at DESC"
    cursor = await db.execute(sql, (user["id"],))
    rows = await cursor.fetchall()
    return [_agent_to_response(row) for row in rows]


@router.post("", response_model=UserAgentCreateResponse, status_code=201)
async def create_my_agent(
    request: Request,
    body: UserAgentCreateRequest,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    local = (body.address_local or name).strip().lower()
    if not _ADDRESS_LOCAL_RE.match(local):
        raise HTTPException(
            status_code=400,
            detail="Address local part must be lowercase letters/digits/._- with alphanumeric on both ends",
        )
    address = f"{local}{_user_domain_suffix(user['username'])}"

    cursor = await db.execute("SELECT id FROM agents WHERE address = ?", (address,))
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Address '{address}' is already taken")

    await _validate_team_ownership(db, body.team_id, user["id"])

    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    raw_key, key_hash = generate_api_key()
    suffix = raw_key[-6:]

    async with db_transaction(db):
        await db.execute(
            """INSERT INTO agents (id, name, address, role, description, system_prompt, tags, user_id, created_at, status, api_key_suffix, team_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (
                agent_id,
                name,
                address,
                body.role or "",
                body.description or "",
                body.system_prompt or "",
                json.dumps(body.tags, ensure_ascii=False),
                user["id"],
                now,
                suffix,
                body.team_id,
            ),
        )
        key_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (key_id, user["id"], key_hash, f"agent:{agent_id}", now),
        )

    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    base = _agent_to_response(row).model_dump()
    base["api_key_plaintext"] = raw_key
    return UserAgentCreateResponse(**base)


@router.get("/{agent_id}", response_model=UserAgentResponse)
async def get_my_agent(
    agent_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"])
    )
    row = await cursor.fetchone()
    # 404 (not 403) so we don't leak existence of agents owned by others.
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_response(row)


@router.put("/{agent_id}", response_model=UserAgentResponse)
async def update_my_agent(
    agent_id: str,
    request: Request,
    body: UserAgentUpdateRequest,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.team_id is not None and body.team_id != "":
        await _validate_team_ownership(db, body.team_id, user["id"])

    fields: list[str] = []
    params: list = []
    if body.role is not None:
        fields.append("role = ?")
        params.append(body.role)
    if body.description is not None:
        fields.append("description = ?")
        params.append(body.description)
    if body.system_prompt is not None:
        fields.append("system_prompt = ?")
        params.append(body.system_prompt)
    if body.tags is not None:
        fields.append("tags = ?")
        params.append(json.dumps(body.tags, ensure_ascii=False))
    if body.team_id is not None:
        fields.append("team_id = ?")
        params.append(body.team_id or None)

    if fields:
        params.append(agent_id)
        async with db_transaction(db):
            await db.execute(
                f"UPDATE agents SET {', '.join(fields)} WHERE id = ?", tuple(params)
            )

    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    return _agent_to_response(await cursor.fetchone())


@router.delete("/{agent_id}")
async def delete_my_agent(
    agent_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT id, status FROM agents WHERE id = ? AND user_id = ?",
        (agent_id, user["id"]),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    if (row["status"] or "active") == "deleted":
        return {"ok": True, "agent_id": agent_id, "already_deleted": True}
    async with db_transaction(db):
        await db.execute(
            "UPDATE agents SET status = 'deleted' WHERE id = ?", (agent_id,)
        )
        await db.execute(
            "UPDATE api_keys SET is_active = 0 WHERE name = ?",
            (f"agent:{agent_id}",),
        )
    return {"ok": True, "agent_id": agent_id}


@router.post(
    "/{agent_id}/regenerate-key", response_model=UserAgentRegenerateKeyResponse
)
async def regenerate_my_agent_key(
    agent_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

    raw_key, key_hash = generate_api_key()
    suffix = raw_key[-6:]
    now = datetime.now(timezone.utc).isoformat()

    async with db_transaction(db):
        await db.execute(
            "UPDATE api_keys SET is_active = 0 WHERE name = ?", (f"agent:{agent_id}",)
        )
        key_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (key_id, user["id"], key_hash, f"agent:{agent_id}", now),
        )
        await db.execute(
            "UPDATE agents SET api_key_suffix = ? WHERE id = ?", (suffix, agent_id)
        )

    return UserAgentRegenerateKeyResponse(
        agent_id=agent_id,
        api_key_masked=_mask_api_key(suffix),
        api_key_plaintext=raw_key,
    )


@router.get("/{agent_id}/export", response_model=UserAgentExportResponse)
async def export_my_agent_md(
    agent_id: str,
    request: Request,
    format: str = Query("agent_md"),
    user: dict = Depends(get_current_user),
):
    if format not in ("agent_md", "soul_md"):
        raise HTTPException(status_code=400, detail="format must be agent_md or soul_md")
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")
    broker_url = get_base_url(request)
    namespace_suffix = _user_domain_suffix(user["username"])
    content = _build_user_agent_md(row, broker_url, namespace_suffix)
    filename = "AGENT.md" if format == "agent_md" else "SOUL.md"
    return UserAgentExportResponse(filename=filename, content=content)
