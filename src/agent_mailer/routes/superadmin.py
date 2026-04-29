import json
import re
import secrets
import string
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from agent_mailer.auth import create_session_token, generate_api_key, hash_api_key
from agent_mailer.config import DOMAIN
from agent_mailer.db import (
    SETTING_INVITE_REQUIRED,
    db_transaction,
    get_invite_required,
    set_setting,
)
from agent_mailer.dependencies import require_superadmin
from agent_mailer.models import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentExportResponse,
    AdminAgentRegenerateKeyResponse,
    AdminAgentResponse,
    AdminAgentUpdateRequest,
    InviteCodeResponse,
    LoginResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    UserResponse,
)
from agent_mailer.utils import get_base_url

router = APIRouter(prefix="/superadmin", tags=["superadmin"])

INVITE_CODE_CHARS = string.ascii_letters + string.digits
INVITE_CODE_LENGTH = 8


def _generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(INVITE_CODE_LENGTH))


@router.post("/invite-codes", response_model=InviteCodeResponse, status_code=201)
async def create_invite_code(
    request: Request, user: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    code = _generate_invite_code()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO invite_codes (code, created_by, created_at) VALUES (?, ?, ?)",
        (code, user["id"], now),
    )
    await db.commit()
    return InviteCodeResponse(
        code=code,
        created_by=user["id"],
        used_by=None,
        used_at=None,
        created_at=now,
    )


@router.get("/invite-codes", response_model=list[InviteCodeResponse])
async def list_invite_codes(
    request: Request, user: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM invite_codes ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [
        InviteCodeResponse(
            code=row["code"],
            created_by=row["created_by"],
            used_by=row["used_by"],
            used_at=row["used_at"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/users", response_model=list[UserResponse])
async def list_users(request: Request, user: dict = Depends(require_superadmin)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM users ORDER BY created_at")
    rows = await cursor.fetchall()
    return [
        UserResponse(
            id=row["id"],
            username=row["username"],
            is_superadmin=bool(row["is_superadmin"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/settings", response_model=SystemSettingsResponse)
async def get_system_settings(request: Request, user: dict = Depends(require_superadmin)):
    db = request.app.state.db
    return SystemSettingsResponse(invite_required=await get_invite_required(db))


@router.put("/settings", response_model=SystemSettingsResponse)
async def update_system_settings(
    request: Request,
    body: SystemSettingsUpdateRequest,
    user: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    await set_setting(db, SETTING_INVITE_REQUIRED, "1" if body.invite_required else "0")
    return SystemSettingsResponse(invite_required=await get_invite_required(db))


ADMIN_AGENT_DOMAIN_SUFFIX = f"@admin.{DOMAIN}"
# First and last chars must be alphanumeric; middle may contain ._- ; total length 1-63.
ADDRESS_LOCAL_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,61}[a-z0-9])?$")


def _mask_api_key(suffix: str) -> str:
    return f"amk_****{suffix}" if suffix else "amk_****"


def _parse_agent_row(row) -> dict:
    d = dict(row)
    raw = d.get("tags", "[]")
    d["tags"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return d


def _agent_to_response(row) -> AdminAgentResponse:
    d = _parse_agent_row(row)
    return AdminAgentResponse(
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


def _build_agent_md(agent_row, broker_url: str, api_key: str | None) -> str:
    """Render the AGENT.md (== SOUL.md) template for a managed agent."""
    name = agent_row["name"]
    role = agent_row["role"] or ""
    address = agent_row["address"]
    agent_id = agent_row["id"]
    system_prompt = agent_row["system_prompt"] or ""
    key = api_key or "<your_api_key>"

    return f"""# Agent Identity

- **Name**: {name}
- **Role**: {role}
- **Address**: {address}
- **Agent ID**: {agent_id}
- **Broker URL**: {broker_url}

## ⚠️ Security Note / 安全须知

All Agents created under the same admin namespace (`@admin.{DOMAIN}`)
share authentication scope. Any agent holding a valid X-API-Key can
theoretically access another agent's mailbox in the same namespace by
passing the target's `agent_id` and `address`. This is by design
(single-admin trust model). **Do NOT distribute admin namespace API
keys outside the trusted team.**

同一 admin 命名空间（`@admin.{DOMAIN}`）下创建的所有 Agent 共享同一鉴权作用域。
持有任意一把有效 X-API-Key 的 Agent，理论上可通过传入目标 `agent_id` 与 `address`
读写同命名空间内其他 Agent 的邮箱。这是设计如此（单一 admin 信任模型）。
**严禁将 admin 命名空间下的 API Key 分发给受信团队之外的成员。**

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


@router.get("/agents", response_model=list[AdminAgentResponse])
async def admin_list_agents(
    request: Request,
    include_deleted: bool = Query(False),
    admin: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    if include_deleted:
        sql = "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at DESC"
        params = (admin["id"],)
    else:
        sql = "SELECT * FROM agents WHERE user_id = ? AND status != 'deleted' ORDER BY created_at DESC"
        params = (admin["id"],)
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    return [_agent_to_response(row) for row in rows]


@router.post("/agents", response_model=AdminAgentCreateResponse, status_code=201)
async def admin_create_agent(
    request: Request,
    body: AdminAgentCreateRequest,
    admin: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    local = (body.address_local or name).strip().lower()
    if not ADDRESS_LOCAL_RE.match(local):
        raise HTTPException(
            status_code=400,
            detail="Address local part must be lowercase letters/digits/._- and start with [a-z0-9]",
        )
    address = f"{local}{ADMIN_AGENT_DOMAIN_SUFFIX}"

    cursor = await db.execute("SELECT id, status FROM agents WHERE address = ?", (address,))
    existing = await cursor.fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Address '{address}' is already taken")

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
                admin["id"],
                now,
                suffix,
                body.team_id,
            ),
        )
        key_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (key_id, admin["id"], key_hash, f"agent:{agent_id}", now),
        )

    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    base = _agent_to_response(row).model_dump()
    base["api_key_plaintext"] = raw_key
    return AdminAgentCreateResponse(**base)


@router.put("/agents/{agent_id}", response_model=AdminAgentResponse)
async def admin_update_agent(
    agent_id: str,
    request: Request,
    body: AdminAgentUpdateRequest,
    admin: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, admin["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

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
        await db.execute(f"UPDATE agents SET {', '.join(fields)} WHERE id = ?", tuple(params))
        await db.commit()

    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    return _agent_to_response(await cursor.fetchone())


@router.delete("/agents/{agent_id}")
async def admin_delete_agent(
    agent_id: str, request: Request, admin: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT id, status FROM agents WHERE id = ? AND user_id = ?", (agent_id, admin["id"])
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    if (row["status"] or "active") == "deleted":
        return {"ok": True, "agent_id": agent_id, "already_deleted": True}
    async with db_transaction(db):
        await db.execute("UPDATE agents SET status = 'deleted' WHERE id = ?", (agent_id,))
        await db.execute(
            "UPDATE api_keys SET is_active = 0 WHERE name = ?", (f"agent:{agent_id}",)
        )
    return {"ok": True, "agent_id": agent_id}


@router.post(
    "/agents/{agent_id}/regenerate-key", response_model=AdminAgentRegenerateKeyResponse
)
async def admin_regenerate_agent_key(
    agent_id: str, request: Request, admin: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, admin["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")

    raw_key, key_hash = generate_api_key()
    suffix = raw_key[-6:]
    now = datetime.now(timezone.utc).isoformat()

    async with db_transaction(db):
        # Invalidate any existing keys for this agent and atomically issue the new one.
        await db.execute(
            "UPDATE api_keys SET is_active = 0 WHERE name = ?", (f"agent:{agent_id}",)
        )
        key_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (key_id, admin["id"], key_hash, f"agent:{agent_id}", now),
        )
        await db.execute(
            "UPDATE agents SET api_key_suffix = ? WHERE id = ?", (suffix, agent_id)
        )

    return AdminAgentRegenerateKeyResponse(
        agent_id=agent_id,
        api_key_masked=_mask_api_key(suffix),
        api_key_plaintext=raw_key,
    )


@router.get("/agents/{agent_id}/export", response_model=AdminAgentExportResponse)
async def admin_export_agent_md(
    agent_id: str,
    request: Request,
    format: str = Query("agent_md"),
    admin: dict = Depends(require_superadmin),
):
    if format not in ("agent_md", "soul_md"):
        raise HTTPException(status_code=400, detail="format must be agent_md or soul_md")
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, admin["id"])
    )
    row = await cursor.fetchone()
    if not row or (row["status"] or "active") == "deleted":
        raise HTTPException(status_code=404, detail="Agent not found")
    broker_url = get_base_url(request)
    content = _build_agent_md(row, broker_url, api_key=None)
    filename = "AGENT.md" if format == "agent_md" else "SOUL.md"
    return AdminAgentExportResponse(filename=filename, content=content)


@router.post("/login-as/{user_id}", response_model=LoginResponse)
async def login_as(
    request: Request,
    response: Response,
    user_id: str,
    admin: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    target_user = await cursor.fetchone()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_session_token(user_id, impersonated_by=admin["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=24 * 3600,
    )
    return LoginResponse(
        token=token,
        user=UserResponse(
            id=target_user["id"],
            username=target_user["username"],
            is_superadmin=bool(target_user["is_superadmin"]),
            created_at=target_user["created_at"],
        ),
    )
