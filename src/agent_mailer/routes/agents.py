import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from agent_mailer.models import AgentRegisterRequest, AgentResponse, AgentSetupResponse, AgentUpdateAddressRequest
from agent_mailer.utils import get_base_url

router = APIRouter()


@router.post("/agents/register", response_model=AgentResponse)
async def register_agent(req: AgentRegisterRequest, request: Request):
    db = request.app.state.db
    agent_id = str(uuid.uuid4())
    address = req.address or f"{req.name}@local"
    now = datetime.now(timezone.utc).isoformat()

    # check address uniqueness
    cursor = await db.execute("SELECT id FROM agents WHERE address = ?", (address,))
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Address '{address}' is already taken")

    await db.execute(
        "INSERT INTO agents (id, name, address, role, description, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (agent_id, req.name, address, req.role, req.description, req.system_prompt, now),
    )
    await db.commit()
    return AgentResponse(
        id=agent_id, name=req.name, address=address, role=req.role,
        description=req.description, system_prompt=req.system_prompt, created_at=now,
    )


@router.patch("/agents/{agent_id}/address", response_model=AgentResponse)
async def update_address(agent_id: str, req: AgentUpdateAddressRequest, request: Request):
    db = request.app.state.db

    # check agent exists
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

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

    agent = dict(row)
    agent["address"] = req.address
    return AgentResponse(**{k: agent[k] for k in AgentResponse.model_fields})


@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents ORDER BY created_at")
    rows = await cursor.fetchall()
    return [AgentResponse(**dict(row)) for row in rows]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(**dict(row))


@router.get("/agents/{agent_id}/setup", response_model=AgentSetupResponse)
async def get_agent_setup(agent_id: str, request: Request):
    """返回该 Agent 的 AGENT.md 内容和 CLAUDE.md 模板，用于工作目录初始化。"""
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
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

你是本地多智能体协作网络中的一个节点。你通过 Mail Broker 与其他 Agent 异步通信。
你的邮箱地址是 `{agent['address']}`，所有收发件均使用此地址。

### 收件 (读取任务)
```
GET {broker_url}/messages/inbox/{agent['address']}?agent_id={agent['id']}
```

### 发件 (发送消息)
```
POST {broker_url}/messages/send
Body: {{"agent_id": "{agent['id']}", "from_agent": "{agent['address']}", "to_agent": "<目标agent地址>", "action": "send|reply|forward", "subject": "...", "body": "...", "parent_id": "<reply/forward 时必填>", "forward_scope": "<可选，仅 forward：message=仅父邮件 | thread=整线（不含已删单封）>"}}
```

### 标记已读
```
PATCH {broker_url}/messages/{{message_id}}/read
PATCH {broker_url}/messages/{{message_id}}/unread
```

### 查看会话线程
```
GET {broker_url}/messages/thread/{{thread_id}}
```

### 查看所有 Agent
```
GET {broker_url}/agents
```
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

    instructions = f"""## 工作目录设置步骤

1. 在你的工作目录下创建 `AGENT.md`，写入上方 agent_md 的内容
2. 创建 `CLAUDE.md`（或对应 Agent 的配置文件），引用 AGENT.md
3. 在该目录下启动 Agent（如 Claude Code），它会自动读取身份配置
"""

    return AgentSetupResponse(
        agent_md=agent_md,
        claude_md=claude_md,
        instructions=instructions,
    )
