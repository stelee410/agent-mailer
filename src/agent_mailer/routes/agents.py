import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from agent_mailer.config import DOMAIN
from agent_mailer.dependencies import get_api_key_user
from agent_mailer.models import AgentRegisterRequest, AgentResponse, AgentSetupResponse, AgentUpdateAddressRequest
from agent_mailer.utils import get_base_url

router = APIRouter()


def _compute_status(last_seen: str | None, role: str | None = None) -> str:
    """Compute agent online status from last_seen timestamp."""
    if role == "operator":
        return "online"
    if not last_seen:
        return "offline"
    try:
        seen = datetime.fromisoformat(last_seen)
        delta = (datetime.now(timezone.utc) - seen).total_seconds()
        if delta <= 60:
            return "online"
        elif delta <= 300:
            return "idle"
        return "offline"
    except (ValueError, TypeError):
        return "offline"


def _parse_agent(row) -> dict:
    """Convert a DB row to a dict with tags parsed from JSON string to list."""
    d = dict(row)
    raw = d.get("tags", "[]")
    d["tags"] = json.loads(raw) if isinstance(raw, str) else raw
    d["last_seen"] = d.get("last_seen")
    d["status"] = _compute_status(d["last_seen"], d.get("role"))
    d["team_id"] = d.get("team_id")
    return d


def _user_domain_suffix(username: str) -> str:
    return f"@{username}.{DOMAIN}"


@router.post("/agents/register", response_model=AgentResponse)
async def register_agent(
    req: AgentRegisterRequest, request: Request, user: dict = Depends(get_api_key_user)
):
    db = request.app.state.db
    agent_id = str(uuid.uuid4())
    suffix = _user_domain_suffix(user["username"])

    if req.address:
        if not req.address.endswith(suffix):
            raise HTTPException(
                status_code=400,
                detail=f"Address must end with '{suffix}'",
            )
        address = req.address
    else:
        address = f"{req.name}{suffix}"

    now = datetime.now(timezone.utc).isoformat()

    # check address uniqueness
    cursor = await db.execute("SELECT id FROM agents WHERE address = ?", (address,))
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Address '{address}' is already taken")

    await db.execute(
        "INSERT INTO agents (id, name, address, role, description, system_prompt, tags, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (agent_id, req.name, address, req.role, req.description, req.system_prompt, "[]", user["id"], now),
    )
    await db.commit()
    return AgentResponse(
        id=agent_id, name=req.name, address=address, role=req.role,
        description=req.description, system_prompt=req.system_prompt, tags=[], created_at=now,
    )


@router.patch("/agents/{agent_id}/address", response_model=AgentResponse)
async def update_address(
    agent_id: str, req: AgentUpdateAddressRequest, request: Request,
    user: dict = Depends(get_api_key_user),
):
    db = request.app.state.db

    # check agent exists and belongs to user
    cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"]))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    suffix = _user_domain_suffix(user["username"])
    if not req.address.endswith(suffix):
        raise HTTPException(
            status_code=400,
            detail=f"Address must end with '{suffix}'",
        )

    # check new address uniqueness (exclude self)
    cursor = await db.execute("SELECT id FROM agents WHERE address = ? AND id != ?", (req.address, agent_id))
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Address '{req.address}' is already taken")

    old_address = row["address"]
    await db.execute("UPDATE agents SET address = ? WHERE id = ?", (req.address, agent_id))

    # update existing messages to reflect new address
    await db.execute("UPDATE messages SET from_agent = ? WHERE from_agent = ?", (req.address, old_address))
    await db.execute("UPDATE messages SET to_agent = ? WHERE to_agent = ?", (req.address, old_address))

    await db.commit()

    agent = _parse_agent(row)
    agent["address"] = req.address
    return AgentResponse(**{k: agent[k] for k in AgentResponse.model_fields})


@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(request: Request, agent_id: str | None = None, user: dict = Depends(get_api_key_user)):
    db = request.app.state.db

    if agent_id:
        # Team-based visibility filtering
        cursor = await db.execute(
            "SELECT team_id FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"])
        )
        agent_row = await cursor.fetchone()
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")

        requester_team_id = agent_row["team_id"]

        if requester_team_id:
            # Return same-team agents + human operators
            cursor = await db.execute(
                "SELECT * FROM agents WHERE user_id = ? AND (team_id = ? OR role = 'operator') ORDER BY created_at",
                (user["id"], requester_team_id),
            )
        else:
            # Ungrouped: return other ungrouped agents + human operators
            cursor = await db.execute(
                "SELECT * FROM agents WHERE user_id = ? AND (team_id IS NULL OR role = 'operator') ORDER BY created_at",
                (user["id"],),
            )
    else:
        # No agent_id — return all (admin/backward compat)
        cursor = await db.execute(
            "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at", (user["id"],)
        )

    rows = await cursor.fetchall()
    return [AgentResponse(**_parse_agent(row)) for row in rows]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request, user: dict = Depends(get_api_key_user)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"]))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(**_parse_agent(row))


@router.get("/agents/{agent_id}/setup", response_model=AgentSetupResponse)
async def get_agent_setup(agent_id: str, request: Request, user: dict = Depends(get_api_key_user)):
    """返回该 Agent 的 AGENT.md 内容和 CLAUDE.md 模板，用于工作目录初始化。"""
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ? AND user_id = ?", (agent_id, user["id"]))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = dict(row)

    broker_url = get_base_url(request)

    agent_md = f"""# Agent Identity

- **Name**: {agent['name']}
- **Role**: {agent['role']}
- **Address**: {agent['address']}
- **Agent ID**: {agent['id']}
- **Broker URL**: {broker_url}

## 身份提示词 (System Prompt)

{agent['system_prompt']}

## 邮箱协议

你是多智能体协作网络中的一个节点。你通过 Mail Broker 与其他 Agent 异步通信。
你的邮箱地址是 `{agent['address']}`，所有收发件均使用此地址。

### 认证
所有 API 请求必须携带 `X-API-Key` 头：
```
X-API-Key: <your_api_key>
```

### 收件 (读取任务)
```
GET {broker_url}/messages/inbox/{agent['address']}?agent_id={agent['id']}
Headers: X-API-Key: <your_api_key>
```

### 发件 (发送消息)
```
POST {broker_url}/messages/send
Headers: X-API-Key: <your_api_key>
Body: {{"agent_id": "{agent['id']}", "from_agent": "{agent['address']}", "to_agent": "<目标agent地址>", "action": "send|reply|forward", "subject": "...", "body": "...", "parent_id": "<reply/forward 时必填>", "forward_scope": "<可选，仅 forward：message=仅父邮件 | thread=整线（不含已删单封）>"}}
```

### 标记已读
```
PATCH {broker_url}/messages/{{message_id}}/read
PATCH {broker_url}/messages/{{message_id}}/unread
Headers: X-API-Key: <your_api_key>
```

### 查看会话线程
```
GET {broker_url}/messages/thread/{{thread_id}}
Headers: X-API-Key: <your_api_key>
```

### 查看所有 Agent
```
GET {broker_url}/agents
Headers: X-API-Key: <your_api_key>
```

## Auto-watch (Claude Code only)

This agent's runtime configuration can be persisted in `.agent-mailer/config.toml`
within this workdir (NOT in the home directory). Each workdir is an
independent agent session.

To enable automatic inbox processing without keeping a human in the loop:

1. Install once: `uv tool install agent-mailer`
2. From this directory: `agent-mailer watch`

On first run, a small wizard prompts you to confirm the agent name, API key,
and pick a permission mode (`acceptEdits` / `bypassPermissions` / `plan`).
Subsequent runs read `.agent-mailer/config.toml` directly without prompting.

State location (all under `<workdir>/.agent-mailer/`, mode 0700):
- `config.toml` — agent identity + API key (mode 0600, gitignored)
- `sessions.json` — thread → claude session mapping (resume continuity)
- `processed.txt` / `cursor.txt` — message dedup
- `memory/` — long-term + per-thread handoff notes
- `log.jsonl` — structured runtime log
- `dead_letter.jsonl` — messages that exhausted retry budget

Subcommand surface: `agent-mailer {{watch, init, doctor, verify, status,
logs, sessions, memory, dead-letter, fetch, test-claude, config}}`. See
`agent-mailer --help`.
"""

    claude_md = f"""# CLAUDE.md

请在启动时加载 AGENT.md 以获取你的身份和通信协议。

@import AGENT.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 AGENT.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址: `{agent['address']}`
"""

    infiniti_md = f"""# INFINITI.md

请在启动时加载 SOUL.md 以获取你的身份和通信协议。

@import SOUL.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 SOUL.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址: `{agent['address']}`
"""

    instructions = f"""## 工作目录设置步骤

1. 在你的工作目录下创建 `AGENT.md`（或 `SOUL.md`，取决于 Agent 类型），写入上方 agent_md 的内容
2. 创建对应 Agent 类型的适配文件：
   - Claude Code → `CLAUDE.md`（引用 AGENT.md）
   - Linkyun Infiniti Agent → `INFINITI.md`（引用 SOUL.md，身份文件保存为 SOUL.md）
   - 其他类型请参考 setup.md 文档
3. 在该目录下启动 Agent（如 Claude Code / Infiniti），它会自动读取身份配置
"""

    return AgentSetupResponse(
        agent_md=agent_md,
        claude_md=claude_md,
        infiniti_md=infiniti_md,
        instructions=instructions,
    )
