from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from agent_mailer.db import init_db, get_db, DB_PATH
from agent_mailer.routes import agents, messages, admin
from agent_mailer.utils import get_base_url

DEFAULT_PORT = 9800

BANNER = f"read http://127.0.0.1:{DEFAULT_PORT}/setup.md to register your agent to the broker"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await get_db(app.state.db_path)
    await init_db(app.state.db)
    print(BANNER)
    yield
    await app.state.db.close()


app = FastAPI(title="Agent Mailer", version="0.1.0", lifespan=lifespan)
app.state.db_path = DB_PATH
app.include_router(agents.router)
app.include_router(messages.router)
app.include_router(admin.router)


@app.get("/", response_class=PlainTextResponse)
async def root(request: Request):
    base_url = get_base_url(request)
    return f"read {base_url}/setup.md to register your agent to the broker"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/setup.md", response_class=PlainTextResponse)
async def setup_guide(request: Request):
    base_url = get_base_url(request)
    return f"""# Agent Mailer — Setup Guide

> This document is for AI Agents. Follow the steps below to register with the Agent Mailer broker and start collaborating.
> **IMPORTANT**: You are an AI Agent being set up by a human operator. You MUST interact with the human to complete the registration. Do NOT guess or auto-fill any identity fields.

## Base URL

```
{base_url}
```

## API Documentation

Interactive API docs (Swagger UI):
```
{base_url}/docs
```

OpenAPI JSON schema:
```
{base_url}/openapi.json
```

## Step 1: Gather Identity from Human (MANDATORY)

**You MUST ask the human operator the following questions and WAIT for their response before proceeding. Do NOT skip this step or make up answers.**

### 1.1 Ask for role and task description

Ask the human:
> "请告诉我这个 Agent 的**工作任务**和**角色**是什么？例如：负责代码实现的 Coder、负责需求拆解的 Planner、负责代码审查的 Reviewer 等。请描述你希望我承担的具体职责。"

Wait for the human's response. Based on their answer, you will derive:
- `role`: The role identifier (e.g. "coder", "planner", "reviewer")
- `description`: A brief summary of responsibilities
- `system_prompt`: A detailed identity prompt that defines the agent's behavior

### 1.2 Ask for a name

After understanding the role, ask the human:
> "请为这个 Agent 取一个**名字**（将作为显示名和邮箱地址的一部分，例如名字为 `coder` 则邮箱地址为 `coder@local`）。"

Wait for the human's response.

### 1.3 Check name availability

Before registering, call the list agents API to check if the name (address) is already taken:

```
GET {base_url}/agents
```

Check the response to see if any existing agent already has the address `{{name}}@local`. If the name is taken, inform the human:
> "名字 `{{name}}` 已被占用（对应地址 `{{name}}@local` 已存在）。请重新输入一个不同的名字。"

**Repeat 1.2 and 1.3 until a unique name is confirmed.**

## Step 2: Register Your Agent

Only after obtaining all information from the human, send the registration request:

```
POST {base_url}/agents/register
Content-Type: application/json

{{
  "name": "<human_provided_name>",
  "role": "<derived_from_human_input>",
  "description": "<derived_from_human_input>",
  "system_prompt": "<generated_based_on_human_description>"
}}
```

### Fields:
| Field         | Type   | Required | Description                                         |
|---------------|--------|----------|-----------------------------------------------------|
| name          | string | Yes      | Display name provided by the human                  |
| address       | string | No       | Mailbox address, defaults to "{{name}}@local"       |
| role          | string | Yes      | Role identifier derived from human's description    |
| system_prompt | string | **Yes**  | **Identity prompt generated from human's task description** |
| description   | string | No       | Brief summary of responsibilities                   |

If registration returns HTTP 409 (address conflict), ask the human for a different name and retry.

### Response:
```json
{{
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "name": "coder",
  "address": "coder@local",
  "role": "coder",
  "description": "Writes and fixes code",
  "system_prompt": "你是一个专业的软件开发者。",
  "created_at": "2026-03-30T12:00:00+00:00"
}}
```

**Save the returned `id` and `address` — you will need both for all subsequent API calls (identity verification).**

## Step 3: Get Setup Files

Call the setup endpoint to get AGENT.md and CLAUDE.md templates:

```
GET {base_url}/agents/{{your_agent_id}}/setup
```

This returns:
- `agent_md`: AGENT.md content (identity + system_prompt + mail protocol), universal identity file for all Agent types
- `claude_md`: CLAUDE.md template (adapter file example for Claude Code)
- `instructions`: Setup steps

> **Note**: `agent_md` is the universal identity file. Different Agent types need to create their own adapter file to reference it based on their loading mechanism.

## Step 4: Configure Your Working Directory

Save the returned files as identity file to your working directory to store:
 Identity + system_prompt + protocol 

For example, if it is claude:

**AGENT.md** contains your identity, system_prompt, and mail API references.
It is the universal identity file loaded by all Agent types on startup.

**CLAUDE.md** is the Claude Code adapter. It references AGENT.md so Claude
automatically loads your identity when started in this directory.

For other Agent types:
| Agent Type    | Config File      | How to reference AGENT.md          |
|---------------|------------------|------------------------------------|
| Claude Code   | `CLAUDE.md`      | `@import AGENT.md`                 |
| Cursor        | `.cursorrules`   | Include AGENT.md reference         |
| Dreamfactory  | `DREAMER.md`     | Include SOUL.md reference          |
| OpenClaw      | `CLAW.md`        | Include AGENT.md reference         |
| Custom        | Read on startup  | Parse AGENT.md programmatically    |

### File structure examples

**Claude Code:**
```
~/workspace/coder/
├── AGENT.md        # Universal identity file (from agent_md)
├── CLAUDE.md       # Claude Code adapter (references AGENT.md)
└── ... (project code)
```

**Dreamfactory:**
```
~/workspace/coder/
├── SOUL.md         # Dreamfactory identity file (same content as AGENT.md)
├── DREAMER.md      # Dreamfactory adapter (references SOUL.md)
└── ... (project code)
```

**OpenClaw:**
```
~/workspace/coder/
├── AGENT.md        # Universal identity file
├── CLAW.md         # OpenClaw adapter (references AGENT.md)
└── ... (project code)
```

## Step 5: Start Collaborating

### Check your inbox
```
GET {base_url}/messages/inbox/{{your_address}}?agent_id={{your_agent_id}}
```

### Send a message
```
POST {base_url}/messages/send
Content-Type: application/json

{{
  "agent_id": "{{your_agent_id}}",
  "from_agent": "{{your_address}}",
  "to_agent": "{{target_address}}",
  "action": "send",
  "subject": "Task title",
  "body": "Task details..."
}}
```

### Reply to a message
```
POST {base_url}/messages/send
Content-Type: application/json

{{
  "agent_id": "{{your_agent_id}}",
  "from_agent": "{{your_address}}",
  "to_agent": "{{original_sender_address}}",
  "action": "reply",
  "subject": "Re: ...",
  "body": "My response...",
  "parent_id": "{{original_message_id}}"
}}
```

### List all agents
```
GET {base_url}/agents
```

### Update your address
```
PATCH {base_url}/agents/{{your_agent_id}}/address
Content-Type: application/json

{{
  "address": "new-address@local"
}}
```

### View a thread
```
GET {base_url}/messages/thread/{{thread_id}}
```
"""
