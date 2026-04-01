# Agent Mailer

本地多智能体异步协作网络 — 基于"异步邮件投递"隐喻的 AI Agent 协作中枢。

![Operator Console](docs/operator-console.png)

## 简介

Agent Mailer 是一套极简、高度可扩展的本地 AI Agent 协作平台。它通过中心化的消息 Broker，让多个 AI 智能体（如需求拆解、代码实现、Code Review）以邮件收发的方式进行异步协作，解决长周期、需要反复迭代的软件自动化开发流程。

兼容第三方独立 Agent（如 Claude Code、Cursor）的无缝接入。

## 核心特性

- **异步邮件协作** — Send / Reply / Forward / Inbox 四大消息原语
- **多智能体编排** — 支持 Planner、Coder、Reviewer 等角色协同工作
- **线程化对话** — 基于 Thread 串联多轮迭代，完整保留上下文
- **身份管理** — Agent 注册、地址分配（`name@local`）、身份验证
- **Web 管理面板** — Operator Console 实时查看所有 Agent 收发状态
- **Claude Code 深度集成** — 内置 CLI 命令（send / check-inbox / reply / forward）
- **零外部依赖** — SQLite 本地存储，开箱即用

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| 数据库 | SQLite + aiosqlite |
| 服务器 | uvicorn |
| 包管理 | uv |

## 快速开始

### 安装依赖

```bash
uv sync
```

### 启动 Broker

```bash
./run.sh
# 或
uv run uvicorn agent_mailer.main:app --port 9800
```

Broker 启动后访问 `http://127.0.0.1:9800/admin/ui` 即可打开 Operator Console。

### 注册 Agent

```bash
curl -X POST http://localhost:9800/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "coder",
    "role": "coder",
    "description": "Code implementation agent",
    "system_prompt": "你是一个专业的软件开发者"
  }'
```

### 发送消息

```bash
curl -X POST http://localhost:9800/messages/send \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "<your-agent-id>",
    "from_agent": "planner@local",
    "to_agent": "coder@local",
    "action": "send",
    "subject": "实现用户登录模块",
    "body": "请按照以下规格实现..."
  }'
```

## API 概览

| 端点 | 说明 |
|------|------|
| `POST /agents/register` | 注册新 Agent |
| `GET /agents` | 列出所有 Agent |
| `GET /agents/{id}/setup` | 获取 Agent 配置文件 |
| `POST /messages/send` | 发送 / 回复 / 转发消息 |
| `GET /messages/inbox/{address}` | 查看收件箱 |
| `GET /messages/thread/{thread_id}` | 查看对话线程 |
| `PATCH /messages/{id}/read` | 标记消息已读 |
| `GET /admin/ui` | Web 管理面板 |
| `GET /docs` | Swagger API 文档 |

## 典型工作流

```
Human ──send──▶ Planner ──forward──▶ Coder ──forward──▶ Reviewer
                                       ▲                    │
                                       └────reply (修改)────┘
```

1. Human 将需求发送给 Planner
2. Planner 拆解需求，转发给 Coder
3. Coder 完成编码，转发给 Reviewer
4. Reviewer 审核，通过则完成；否则回复修改意见给 Coder 继续迭代

## 运行测试

```bash
uv run pytest tests/ -v
```

## 许可证

MIT
