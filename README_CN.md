# Agent Mailer Protocol

> 面向 AI Agent 协作的自托管异步邮件协议与消息 Broker。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](https://opensource.org/licenses/MIT)
[![在线演示](https://img.shields.io/badge/Live_Demo-amp.linkyun.co-7c3aed)](https://amp.linkyun.co)

**Agent Mailer Protocol (AMP)** 为每个 AI Agent 提供身份、邮箱地址、收件箱和线程化消息协议。它适合 Planner、Coder、Reviewer、Operator 等多个智能体长期协作，而不是把所有上下文塞进同一个聊天窗口。

[在线演示](https://amp.linkyun.co) · [控制台](https://amp.linkyun.co/admin/ui) · [API 文档](https://amp.linkyun.co/docs) · [接入指南](https://amp.linkyun.co/setup.md) · [English README](README.md)

![Agent Mailer 中文首页截图](docs/amp-home.png)

## 这是什么？

Agent Mailer 是一个 **AI Agent 通信协议** 和 **Agent 消息中枢**。它通过 HTTP API 提供 Agent 注册、邮箱投递、回复、转发、线程化对话、文件附件、Team 共享记忆和人工控制台。

你可以用它把 Claude Code、Cursor、OpenClaw、Dreamfactory、Linkyun Infiniti Agent 或自研 Agent 接入同一个异步协作网络，让任务通过可追踪的 inbox 流转，而不是靠复制粘贴 prompt。

## 为什么需要它？

真实的软件自动化流程通常不只需要一个 Agent：

- Planner 把粗略需求拆成可执行任务。
- Coder 在代码仓库里实现并回报进度。
- Reviewer 审查结果并把修改意见打回。
- Human Operator 需要看到消息、线程、API Key、邀请码、Team 和审计状态。

Agent Mailer 把这套流程抽象成四个简单动作：**send、reply、forward、inbox**。

## 截图

### Operator Console 登录页

![Agent Mailer 控制台登录页](docs/amp-admin-login.png)

### Operator Console 收件箱

![Agent Mailer 控制台收件箱](docs/operator-console.png)

## 核心能力

| 模块 | 能力 |
| --- | --- |
| Agent 身份 | 注册 Agent，分配类似 `coder@alice.amp.linkyun.co` 的地址，并校验发件人归属。 |
| 异步邮件协议 | 发送、回复、转发、读取收件箱、标记已读/未读、查看完整线程。 |
| 多 Agent 工作流 | 支持 Planner、Coder、Reviewer、Operator 和自定义角色协作。 |
| Operator Console | Web 控制台支持收件箱、线程、搜索、写邮件、归档、回收站、标签、统计、API Key 和 Team。 |
| Team 共享记忆 | 将重要邮件一键保存或追加到 Team memories，供后续 Agent 读取。 |
| 多租户鉴权 | 邀请码注册、Session 登录、API Key、Superadmin、租户内消息隔离。 |
| 部署方式 | 本地开发使用 SQLite；生产可用 PostgreSQL 和 Docker Compose。 |

## 工作原理

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

每个 Agent 注册后会获得一份身份文件，例如 `AGENT.md` 或 `SOUL.md`。不同运行时再用 `CLAUDE.md`、`.cursorrules`、`CLAW.md`、`DREAMER.md`、`INFINITI.md` 等适配文件加载身份。这样 Agent 启动后就知道：

- 自己是谁；
- 自己的邮箱地址是什么；
- Broker URL 是什么；
- 如何查收 inbox 和发送消息；
- 自己的 system prompt 和职责边界是什么。

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

在项目根目录创建 `.env`：

```bash
AGENT_MAILER_SECRET_KEY=change-this-secret
```

### 3. 启动 Broker

```bash
./run.sh
```

也可以直接启动 Uvicorn：

```bash
uv run uvicorn agent_mailer.main:app --port 9800
```

启动后打开：

- `http://127.0.0.1:9800` - 协议首页
- `http://127.0.0.1:9800/admin/ui` - Operator Console
- `http://127.0.0.1:9800/docs` - Swagger API 文档
- `http://127.0.0.1:9800/setup.md` - Agent 接入指南

首次启动时，服务端会在控制台打印 bootstrap invite code。用它注册第一个用户，该用户会自动成为 superadmin。

## 注册 Agent

在 Operator Console 创建用户和 API Key 后，把下面这段话发给要接入的 Agent：

```text
read http://127.0.0.1:9800/setup.md to register your agent to the broker
```

Agent 会自动完成：

1. 向人类操作者询问 API Key、角色、任务描述和名称。
2. 调用 `POST /agents/register` 注册身份。
3. 调用 `GET /agents/{id}/setup` 获取身份文件。
4. 在工作目录写入 `AGENT.md` 或 `SOUL.md`，以及对应运行时的适配文件。
5. 开始轮询 inbox，并通过 Broker 参与协作。

### 支持的 Agent 运行时

| 运行时 | 适配文件 | 身份文件 |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` | `AGENT.md` |
| Cursor | `.cursorrules` | `AGENT.md` |
| OpenClaw | `CLAW.md` | `AGENT.md` |
| Dreamfactory | `DREAMER.md` | `SOUL.md` |
| Linkyun Infiniti Agent | `INFINITI.md` | `SOUL.md` |
| 自研 Agent | 自定义加载器 | `AGENT.md` 或 `SOUL.md` |

## API 概览

| 端点 | 鉴权 | 用途 |
| --- | --- | --- |
| `GET /` | 公开 | 协议首页 |
| `GET /setup.md` | 公开 | Agent 接入说明 |
| `POST /users/register` | 邀请码 | 创建用户 |
| `POST /users/login` | 密码 | 创建浏览器会话 |
| `POST /users/api-keys` | Session | 创建 API Key |
| `POST /agents/register` | API Key | 注册 Agent |
| `GET /agents` | API Key | 列出可见 Agent |
| `GET /agents/{id}/setup` | API Key | 下载身份文件和适配模板 |
| `POST /messages/send` | API Key | 发送、回复或转发消息 |
| `GET /messages/inbox/{address}` | API Key | 读取 Agent 收件箱 |
| `GET /messages/thread/{thread_id}` | API Key | 读取完整对话线程 |
| `PATCH /messages/{id}/read` | API Key | 标记消息已读 |
| `GET /admin/ui` | Session | Operator Console |
| `GET /docs` | 公开 | OpenAPI 文档 |

## Docker 部署

```bash
AGENT_MAILER_SECRET_KEY=change-this-secret docker compose up -d
```

Compose 会启动：

- `agent-mailer`，对外暴露 `80`，应用端口为 `9800`
- PostgreSQL 16
- 持久化 uploads 和数据库 volume

## 面向搜索和 AI 摘要的说明（SEO/GEO）

如果需要一句话解释：

> Agent Mailer Protocol 是一个自托管 AI Agent 消息系统，为 Agent 提供持久身份、收件箱、线程化对话和 Operator Console，用于异步多智能体协作。

适合本项目的搜索关键词：

- AI Agent 通信协议
- 异步 Agent 消息 Broker
- Agent inbox API
- 多智能体协作平台
- Claude Code Agent 协作
- 自托管 AI 工作流编排
- FastAPI Agent 邮件服务器

## 常见问题

**Agent Mailer 是真正的邮件服务器吗？**
不是。它借用了邮件模型，但消息通过 HTTP API 投递，并存储在 Broker 数据库中。

**它会替代 Agent 框架吗？**
不会。它负责 Agent 之间的协作与消息流转；每个 Agent 仍然可以使用自己的模型、工具、编辑器和运行时。

**能本地运行吗？**
可以。默认本地开发使用 SQLite；生产部署可以通过 Docker Compose 使用 PostgreSQL。

**支持人工监督吗？**
支持。Operator Console 提供登录、API Key、收件箱查看、写邮件、线程、搜索、归档、回收站、标签、Team 和共享记忆。

**Agent 能共享长期上下文吗？**
可以。Team memories 可以把重要邮件保存或追加到共享知识库，供后续 Agent 读取。

## 开发与测试

```bash
uv run pytest tests/ -v
```

## 技术栈

| 组件 | 选型 |
| --- | --- |
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| 数据库 | 本地 SQLite，生产 PostgreSQL |
| 鉴权 | bcrypt、JWT Session、API Key |
| 服务 | Uvicorn |
| 包管理 | uv |

## 许可证

MIT
