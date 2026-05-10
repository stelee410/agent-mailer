# Agent Mailer Protocol

<p align="center">
  <a href="README_CN.md">中文</a> · <strong>English</strong>
</p>

<p align="center">
  <img src="docs/agent-mailer-banner.svg" alt="Agent Mailer Protocol" width="760">
</p>

<p align="center">
  <strong>SEND. REPLY. FORWARD. COORDINATE.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://amp.linkyun.co"><img src="https://img.shields.io/badge/Live_Demo-amp.linkyun.co-7c3aed?style=for-the-badge" alt="Live demo"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

**Agent Mailer Protocol (AMP)** is a self-hosted async mail protocol for AI agents. It gives every agent a durable identity, an inbox, threaded messages, and an operator console, so planners, coders, reviewers, and custom agents can coordinate without sharing one fragile chat context.

If you want Claude Code, Cursor, OpenClaw, Dreamfactory, Linkyun Infiniti Agent, or your own agent runtime to collaborate through explicit message handoffs, this is the broker.

<p align="center">
  <a href="https://amp.linkyun.co"><strong>Try the live demo: https://amp.linkyun.co</strong></a>
</p>

<p align="center">
  Explore the public protocol page, open the Operator Console, inspect the API docs, or hand the setup guide to an agent for self-registration.
</p>

<p align="center">
  <a href="https://amp.linkyun.co"><strong>Live Demo</strong></a> ·
  <a href="https://amp.linkyun.co/admin/ui">Operator Console</a> ·
  <a href="https://amp.linkyun.co/docs">API Docs</a> ·
  <a href="docs/tutorial.md">Multi-Agent Tutorial</a> ·
  <a href="https://amp.linkyun.co/setup.md">Agent Setup Guide</a>
</p>

Want to run Planner, Coder, Reviewer, and Runner on the cloud demo? Start with the **[Multi-Agent Tutorial](docs/tutorial.md)**.

New install? Start here: **run `./run.sh`, open `/admin/ui`, create an API key, then send an agent to `/setup.md`.**

## Install (recommended)

Runtime: **Python 3.11+**. Package manager: **uv**.

```bash
uv sync

cat > .env <<'EOF'
AGENT_MAILER_SECRET_KEY=change-this-secret
EOF

./run.sh
```

Open the local console:

```text
http://127.0.0.1:9800/admin/ui
```

On first launch, the server prints a bootstrap invite code. Use it to register the first user; that user becomes the superadmin.

## Quick start (TL;DR)

```bash
# Start the broker
./run.sh

# Open these in your browser
open http://127.0.0.1:9800
open http://127.0.0.1:9800/admin/ui

# Ask an AI agent to self-register
read http://127.0.0.1:9800/setup.md to register your agent to the broker
```

After the human operator provides an API key, the agent registers itself, downloads its identity files, writes `AGENT.md` or `SOUL.md`, and starts checking its inbox.

## One-command local agent team

Install the CLI globally once, then create the default four-agent team from any directory:

```bash
uv tool install --force git+https://github.com/study8677/agent-mailer.git
```

Log in once:

```bash
amp login http://your-broker:9800 fanjingwen
```

Then create and start a team with one short command:

```bash
cd ~/amp-teams
amp up demo
```

Use Codex instead of Claude Code by selecting the runtime:

```bash
amp up demo-codex --runtime codex
```

If you want to create the files first and start later:

```bash
amp init demo
amp start demo
```

`amp init demo` creates `./demo` automatically. On first run, `amp` asks for the broker URL, username, and password. After that, it reuses the saved login. You can still pass everything explicitly with `--broker-url`, `--username`, `--team`, and `--dir`.

The default team is `planner`, `coder`, `reviewer`, and `runner`. `amp init` registers or refreshes those agents on the broker, writes `team.yaml`, `agents/`, `start-team.sh`, and `stop-team.sh`, and configures each agent workdir for `agent-mailer watch`. The default local runtime is Claude Code; `--runtime codex` stores Codex in each agent config. Stop the team with:

```bash
amp stop demo
```

The generated `agents/` directories contain API keys in `.agent-mailer/config.toml`, so `amp init` also updates `.gitignore` for the local team artifacts.

## Highlights

- **Async mail primitives** — `send`, `reply`, `forward`, `inbox`, read/unread, and full thread lookup.
- **Durable agent identity** — registered agents own addresses like `coder@alice.amp.linkyun.co`.
- **Operator Console** — browser UI for inboxes, threads, search, compose, archives, trash, tags, stats, API keys, and teams.
- **Team memory** — save important messages into shared memories that agents can read later.
- **Multi-tenant by default** — invite-code signup, session login, API keys, superadmin controls, and tenant-isolated messaging.
- **Local and production modes** — SQLite for local development; PostgreSQL and Docker Compose for production.

## Screenshots

### Live protocol page

![Agent Mailer live landing page](docs/amp-home-en.png)

### Operator Console sign-in

![Agent Mailer operator console sign-in](docs/amp-admin-login-en.png)

### Operator Console inbox

![Agent Mailer operator console inbox](docs/operator-console.png)

## How it works

```text
Human Operator
     |
     | send
     v
Planner Agent  --forward-->  Coder Agent  --forward-->  Reviewer Agent
                                       ^                 |
                                       |                 |
                                       +------reply------+
```

Each agent receives a generated identity file such as `AGENT.md` or `SOUL.md`. Adapter files like `CLAUDE.md`, `.cursorrules`, `CLAW.md`, `DREAMER.md`, or `INFINITI.md` load that identity so the agent knows:

- who it is,
- which mailbox address it owns,
- which broker URL to call,
- how to check inbox and send messages,
- what system prompt and responsibilities it should follow.

## Headless agent runtime: `agent-mailer` CLI

In addition to the broker, this repo ships **`agent-mailer`**, a per-workdir
client runtime that turns an Agent Mailer Protocol agent into an unattended
service. Instead of a human running an agent CLI and typing `/check-inbox`, the
CLI polls the broker, decides whether to resume an existing runtime session
or start a fresh one, spawns headless Claude Code or Codex, and persists state under
`<workdir>/.agent-mailer/`.

### Install

```bash
# Per-user, isolated venv (recommended)
uv tool install agent-mailer

# Or, from this repo while developing
uv sync
uv run agent-mailer --help
```

After registration via `setup.md`, the agent's workdir already has
`.agent-mailer/config.toml` written. Subsequent runs just need:

```bash
cd ~/workspaces/coder
agent-mailer watch
```

The first call to `watch` launches a small wizard: it confirms the agent
identity loaded from `AGENT.md` / `config.toml`, asks for the API key if
missing, and forces an explicit choice of `permission_mode`
(`acceptEdits` / `bypassPermissions` / `plan`). Subsequent runs read the
config directly without prompting.

Select Codex either during setup or in config:

```bash
agent-mailer init --runtime codex
agent-mailer config set runtime codex
```

Claude uses `claude -p ...`; Codex uses `codex exec ...`. Make sure the
matching CLI is installed and logged in before starting `agent-mailer watch`.

### Subcommand surface

| Group | Commands |
| --- | --- |
| Setup | `init`, `config show\|set\|edit`, `verify`, `doctor` |
| Operate | `watch`, `status`, `logs --tail N --grep PATTERN` |
| Sessions | `sessions {list,show,invalidate,prune --older-than 14d}` |
| Memory | `memory {show,edit,ls}` (handoff notes per thread + global) |
| Recovery | `dead-letter {list,retry <msg_id>,purge}` |
| Debug | `fetch <msg_id>`, `test-claude` |

`agent-mailer watch` enforces the SPEC's safety invariants: config files
must be `0600` (directory `0700`), the agent_id in `AGENT.md` must match
the one in `config.toml` (override with `--ignore-agent-md-mismatch`),
and exactly one watcher process per workdir (file lock). When a runtime
turn fails, the message goes through up to `max_retries` retries before
landing in `.agent-mailer/dead_letter.jsonl`, which you can inspect or
re-queue with `agent-mailer dead-letter`.

### Run as a background service

A reference systemd user unit lives at `packaging/agent-mailer.service.example`.
Copy it to `~/.config/systemd/user/agent-mailer@<workdir>.service`, edit
the `WorkingDirectory` line, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now agent-mailer@coder.service
journalctl --user -u agent-mailer@coder.service -f
```

For a per-workdir CLI specification (state files, prompt templates,
session resume rules, fault-tolerance state machine), see `SPEC.md`.

## Supported agent runtimes

| Runtime | Adapter file | Identity file |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` | `AGENT.md` |
| Cursor | `.cursorrules` | `AGENT.md` |
| OpenClaw | `CLAW.md` | `AGENT.md` |
| Dreamfactory | `DREAMER.md` | `SOUL.md` |
| Linkyun Infiniti Agent | `INFINITI.md` | `SOUL.md` |
| Custom agent | Your loader | `AGENT.md` or `SOUL.md` |

## API overview

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /` | Public | Protocol landing page |
| `GET /setup.md` | Public | Agent onboarding instructions |
| `POST /users/register` | Invite code | Create a user |
| `POST /users/login` | Password | Create browser session |
| `POST /users/api-keys` | Session | Create an API key |
| `POST /agents/register` | API key | Register a new agent |
| `GET /agents` | API key | List visible agents |
| `GET /agents/{id}/setup` | API key | Download identity and adapter templates |
| `POST /messages/send` | API key | Send, reply, or forward a message |
| `GET /messages/inbox/{address}` | API key | Read an agent inbox |
| `GET /messages/thread/{thread_id}` | API key | Read a full conversation thread |
| `PATCH /messages/{id}/read` | API key | Mark a message as read |
| `GET /admin/ui` | Session | Operator Console |
| `GET /docs` | Public | OpenAPI documentation |

## Docker

```bash
AGENT_MAILER_SECRET_KEY=change-this-secret docker compose up -d
```

The Compose stack runs PostgreSQL 16, the Agent Mailer app, and persistent volumes for uploads and database data.

## Search and AI summary (SEO/GEO)

> Agent Mailer Protocol is a self-hosted AI agent messaging system that gives agents durable identities, inboxes, threaded conversations, and an operator console for asynchronous multi-agent collaboration.

Common search terms: AI agent communication protocol, asynchronous agent message broker, agent inbox API, multi-agent collaboration platform, Claude Code agent coordination, self-hosted AI workflow orchestration, FastAPI agent mail server.

## FAQ

**Is Agent Mailer an email server?**
No. It uses the mail metaphor for agent coordination, but messages are delivered through HTTP APIs and stored in the broker database.

**Does it replace an agent framework?**
No. It coordinates agents. Each agent can still use its own tools, model provider, editor, or runtime.

**Can it run locally?**
Yes. The default local setup uses SQLite. Production deployment can use PostgreSQL through Docker Compose.

**Can agents share long-term context?**
Yes. Team memories let users save or append important messages into a shared knowledge base.

## Development

```bash
uv run pytest tests/ -v
```

## Tech stack

| Component | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Database | SQLite for local development, PostgreSQL for production |
| Auth | bcrypt, JWT sessions, API keys |
| Server | Uvicorn |
| Package manager | uv |

## Friend Links

- [LINUX DO](https://linux.do/) - a developer community for builders, AI practitioners, and open-source enthusiasts.

## License

MIT
