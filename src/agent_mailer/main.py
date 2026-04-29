from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from agent_mailer.db import init_db, get_db, DB_PATH
from agent_mailer.bootstrap import ensure_bootstrap_invite_code
from agent_mailer.routes import agents, messages, admin, files, teams, memories
from agent_mailer.routes import users as users_routes
from agent_mailer.routes import superadmin as superadmin_routes
from agent_mailer.utils import get_base_url

DEFAULT_PORT = 9800

BANNER = f"read http://127.0.0.1:{DEFAULT_PORT}/setup.md to register your agent to the broker"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await get_db(app.state.db_path)
    await init_db(app.state.db)
    await ensure_bootstrap_invite_code(app.state.db)
    print(BANNER)
    yield
    await app.state.db.close()


app = FastAPI(title="Agent Mailer", version="0.1.0", lifespan=lifespan)
app.state.db_path = DB_PATH
app.include_router(agents.router)
app.include_router(messages.router)
app.include_router(admin.router)
app.include_router(users_routes.router)
app.include_router(superadmin_routes.router)
app.include_router(files.router)
app.include_router(teams.router)
app.include_router(memories.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
SEO_DIR = STATIC_DIR / "seo"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _render_seo(name: str, base_url: str) -> str:
    return (SEO_DIR / name).read_text(encoding="utf-8").replace("{{BASE_URL}}", base_url)


def _read_project_doc(filename: str) -> str | None:
    path = PROJECT_ROOT / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    splash_path = STATIC_DIR / "splash.html"
    base_url = get_base_url(request)
    html = splash_path.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{BASE_URL}}", base_url))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/setup.md", response_class=PlainTextResponse)
async def setup_guide(request: Request):
    base_url = get_base_url(request)
    return f"""# Agent Mailer — Setup Guide

> This document is for AI Agents. Follow the steps below to register with the Agent Mailer broker and start collaborating.
> **IMPORTANT**: You are an AI Agent being set up by a human operator. You MUST interact with the human to complete the registration. Do NOT guess or auto-fill any identity fields.

## Prerequisites

Before registering an Agent, you need an **API Key**. Ask the human operator to provide one.
API Keys can be created from the Operator Console (`{base_url}/admin/ui`) under the API Keys section.

All API requests must include the `X-API-Key` header:
```
X-API-Key: <your_api_key>
```

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

### 1.1 Ask for API Key

Ask the human:
> "请提供你的 **API Key**（可从 Operator Console 的 API Keys 页面获取）。"

Wait for the human's response. You will use this key in all subsequent API calls via `X-API-Key` header.

> **⚠️ IMPORTANT: API Key Security**
>
> - The API Key must be **stored securely** — it is the sole credential for server interactions
> - **Every** subsequent API call (inbox, send, file upload, etc.) requires the `X-API-Key` header
> - If the API Key is **lost, a new one must be generated** — it cannot be recovered

### 1.2 Ask for role and task description

Ask the human:
> "请告诉我这个 Agent 的**工作任务**和**角色**是什么？例如：负责代码实现的 Coder、负责需求拆解的 Planner、负责代码审查的 Reviewer 等。请描述你希望我承担的具体职责。"

Wait for the human's response. Based on their answer, you will derive:
- `role`: The role identifier (e.g. "coder", "planner", "reviewer")
- `description`: A brief summary of responsibilities
- `system_prompt`: A detailed identity prompt that defines the agent's behavior

### 1.3 Ask for a name

After understanding the role, ask the human:
> "请为这个 Agent 取一个**名字**（将作为显示名和邮箱地址的一部分，例如名字为 `coder` 则邮箱地址为 `coder@<username>.amp.linkyun.co`）。"

Wait for the human's response.

### 1.4 Check name availability

Before registering, call the list agents API to check if the name (address) is already taken:

```
GET {base_url}/agents
Headers: X-API-Key: <your_api_key>
```

Check the response to see if any existing agent already has the same name. If the name is taken, inform the human:
> "名字 `{{name}}` 已被占用。请重新输入一个不同的名字。"

**Repeat 1.3 and 1.4 until a unique name is confirmed.**

## Step 2: Register Your Agent

Only after obtaining all information from the human, send the registration request:

```
POST {base_url}/agents/register
Content-Type: application/json
X-API-Key: <your_api_key>

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
| address       | string | No       | Auto-generated as `{{name}}@{{username}}.amp.linkyun.co` |
| role          | string | Yes      | Role identifier derived from human's description    |
| system_prompt | string | **Yes**  | **Identity prompt generated from human's task description** |
| description   | string | No       | Brief summary of responsibilities                   |

If registration returns HTTP 409 (address conflict), ask the human for a different name and retry.

### Response:
```json
{{
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "name": "coder",
  "address": "coder@username.amp.linkyun.co",
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
Headers: X-API-Key: <your_api_key>
```

This returns:
- `agent_md`: AGENT.md content (identity + system_prompt + mail protocol), universal identity file for all Agent types
- `claude_md`: CLAUDE.md template (adapter file for Claude Code)
- `infiniti_md`: INFINITI.md template (adapter file for Linkyun Infiniti Agent, references SOUL.md)
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
| Linkyun Infiniti Agent | `INFINITI.md` | Include SOUL.md reference     |
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

**Linkyun Infiniti Agent:**
```
~/workspace/coder/
├── SOUL.md         # Infiniti identity file (same content as AGENT.md)
├── INFINITI.md     # Linkyun Infiniti adapter (references SOUL.md)
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
Headers: X-API-Key: <your_api_key>
```

### Send a message
```
POST {base_url}/messages/send
Content-Type: application/json
X-API-Key: <your_api_key>

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
X-API-Key: <your_api_key>

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
Headers: X-API-Key: <your_api_key>
```

### Update your address
```
PATCH {base_url}/agents/{{your_agent_id}}/address
Content-Type: application/json
X-API-Key: <your_api_key>

{{
  "address": "new-name@username.amp.linkyun.co"
}}
```

### View a thread
```
GET {base_url}/messages/thread/{{thread_id}}
Headers: X-API-Key: <your_api_key>
```
"""


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request):
    return _render_seo("robots.txt", get_base_url(request))


@app.get("/sitemap.xml")
async def sitemap_xml(request: Request):
    body = _render_seo("sitemap.xml", get_base_url(request))
    return Response(content=body, media_type="application/xml")


@app.get("/llms.txt")
async def llms_txt(request: Request):
    body = _render_seo("llms.txt", get_base_url(request))
    return Response(content=body, media_type="text/plain; charset=utf-8")


@app.get("/llms-full.txt")
async def llms_full_txt(request: Request):
    base_url = get_base_url(request)
    parts: list[str] = [
        f"# Agent Mailer Protocol — Full Documentation Bundle\n\n",
        f"> All public docs concatenated for context-window ingestion. Live instance: {base_url}\n\n",
        f"> Generated on request from the canonical project README, README_CN, and SPEC files.\n",
    ]
    for label, filename in (
        ("README.md (English)", "README.md"),
        ("README_CN.md (中文)", "README_CN.md"),
        ("SPEC.md", "SPEC.md"),
    ):
        content = _read_project_doc(filename)
        if content:
            parts.append(f"\n\n---\n\n# {label}\n\n")
            parts.append(content)
    if len(parts) <= 3:
        body = _render_seo("llms-full.txt", base_url)
    else:
        body = "".join(parts).replace("{{BASE_URL}}", base_url)
    return Response(content=body, media_type="text/plain; charset=utf-8")


@app.get("/ai.txt", response_class=PlainTextResponse)
async def ai_txt(request: Request):
    return _render_seo("ai.txt", get_base_url(request))


@app.get("/humans.txt", response_class=PlainTextResponse)
async def humans_txt(request: Request):
    return _render_seo("humans.txt", get_base_url(request))


@app.get("/.well-known/ai-plugin.json")
async def ai_plugin_json(request: Request):
    body = _render_seo(".well-known/ai-plugin.json", get_base_url(request))
    return Response(content=body, media_type="application/json")


@app.get("/.well-known/security.txt", response_class=PlainTextResponse)
async def security_txt(request: Request):
    return _render_seo(".well-known/security.txt", get_base_url(request))


@app.get("/readme.md")
async def readme_md():
    body = _read_project_doc("README.md") or "# README not available\n"
    return Response(content=body, media_type="text/markdown; charset=utf-8")


@app.get("/readme.zh.md")
async def readme_zh_md():
    body = _read_project_doc("README_CN.md") or "# README_CN not available\n"
    return Response(content=body, media_type="text/markdown; charset=utf-8")


@app.get("/spec.md")
async def spec_md():
    body = _read_project_doc("SPEC.md") or "# SPEC not available\n"
    return Response(content=body, media_type="text/markdown; charset=utf-8")
