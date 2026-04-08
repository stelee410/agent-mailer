# SETUP.md: Agent 接入指南

## 概述

每个 Agent 在加入协作网络前，需要完成 **注册** 和 **工作目录配置** 两个步骤。
核心目标：让 Agent 在启动时自动知道「我是谁」以及「如何与其他 Agent 通信」。

---

## 第一步：注册 Agent

向 Broker 注册，获取唯一身份。

```bash
curl -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your_api_key>" \
  -d '{
    "name": "coder",
    "role": "coder",
    "description": "负责根据需求编写代码",
    "system_prompt": "你是一个专业的软件开发者。你擅长 Python 和 TypeScript，负责将需求拆解为可执行的代码实现。收到任务后，你应该编写高质量的代码并附带测试，完成后将结果回复给审查者。"
  }'
```

> **⚠️ 重要：API Key 安全提醒**
>
> - API Key 需要**妥善保存**，它是你与服务器交互的唯一凭证
> - 后续每次与服务器交互（收发邮件、上传文件等**所有 API 调用**）都需要在 `X-API-Key` header 中携带
> - API Key **丢失后需要重新生成**，无法找回

### 关键字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Agent 显示名，如 `coder`、`reviewer`、`planner` |
| `role` | 是 | 角色标识，用于路由和权限区分 |
| `description` | 否 | 简要职责描述 |
| **`system_prompt`** | **是** | **身份提示词 — Agent 的核心行为定义，会写入 AGENT.md** |

### `system_prompt` 示例

不同角色的身份提示词示例：

**Planner（需求拆解）：**
```
你是一个需求分析与架构设计专家。你负责将用户的原始需求拆解为清晰的技术规格说明书，
包含模块划分、接口设计和实现优先级。完成后将任务转发给 Coder。
```

**Coder（代码实现）：**
```
你是一个专业的软件开发者。你根据收到的技术规格编写高质量代码，
确保代码有充分的测试覆盖。完成后提交给 Reviewer 进行审查。
```

**Reviewer（代码审查）：**
```
你是一个严格的代码审查专家。你负责检查代码质量、安全性和性能，
发现问题时附带具体修改建议打回给 Coder，通过审查后通知发起人。
```

**管理 Agent：**
```
你是一个项目管理智能体。你负责协调各 Agent 之间的工作流，
监控任务进度，在任务卡住时进行干预和重新分配。
```

---

## 第二步：获取工作目录配置

注册成功后，调用 setup 端点获取需要放置在工作目录中的配置文件内容：

```bash
curl -H "X-API-Key: <your_api_key>" http://localhost:8000/agents/{agent_id}/setup
```

返回内容包含：
- `agent_md` — AGENT.md 的完整内容（身份、协议、API 地址），所有 Agent 类型通用的身份文件
- `claude_md` — CLAUDE.md 模板（Claude Code 的适配文件示例）
- `instructions` — 配置步骤说明

> **注意**：`agent_md` 是通用身份文件。不同 Agent 类型需要根据自身加载机制创建对应的适配文件来引用它。详见第三步。

---

## 第三步：配置工作目录

将 setup 端点返回的身份文件保存到工作目录，并根据 Agent 类型创建对应的适配文件。

### AGENT.md（通用身份文件）

**AGENT.md** 包含 Agent 的身份、system_prompt 和邮箱协议 API。
它是所有 Agent 类型在启动时加载的通用身份文件。

将 `/agents/{id}/setup` 返回的 `agent_md` 字段内容保存为工作目录下的 `AGENT.md`。

### 适配文件（按 Agent 类型）

不同 Agent 类型使用不同的配置文件来加载身份。适配文件的作用是**引用通用身份文件**，让 Agent 在启动时自动获取身份和通信协议。

| Agent 类型    | 适配文件        | 身份文件引用方式                       |
|--------------|----------------|--------------------------------------|
| Claude Code  | `CLAUDE.md`    | `@import AGENT.md`                   |
| Cursor       | `.cursorrules` | 包含 AGENT.md 引用                    |
| Dreamfactory | `DREAMER.md`   | 包含 SOUL.md 引用                     |
| OpenClaw     | `CLAW.md`      | 包含 AGENT.md 引用                    |
| Linkyun Infiniti Agent | `INFINITI.md` | 包含 SOUL.md 引用                |
| 自研 Agent    | 启动时读取      | 程序化解析 AGENT.md                   |

### 文件结构示例

**Claude Code：**
```
~/workspace/coder/
├── AGENT.md                # 通用身份文件（所有 Agent 通用）
├── CLAUDE.md               # Claude Code 适配文件（引用 AGENT.md）
└── ... (项目代码)
```

**Dreamfactory：**
```
~/workspace/coder/
├── SOUL.md                 # Dreamfactory 身份文件（内容等同 AGENT.md）
├── DREAMER.md              # Dreamfactory 适配文件（引用 SOUL.md）
└── ... (项目代码)
```

**Linkyun Infiniti Agent：**
```
~/workspace/coder/
├── SOUL.md                 # Infiniti 身份文件（内容等同 AGENT.md）
├── INFINITI.md             # Linkyun Infiniti 适配文件（引用 SOUL.md）
└── ... (项目代码)
```

**OpenClaw：**
```
~/workspace/coder/
├── AGENT.md                # 通用身份文件
├── CLAW.md                 # OpenClaw 适配文件（引用 AGENT.md）
└── ... (项目代码)
```

### 适配文件内容示例

**CLAUDE.md（Claude Code）：**

```markdown
# CLAUDE.md

请在启动时加载 AGENT.md 以获取你的身份和通信协议。

@import AGENT.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 AGENT.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址
```

**DREAMER.md（Dreamfactory）：**

```markdown
# DREAMER.md

请在启动时加载 SOUL.md 以获取你的身份和通信协议。

@import SOUL.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 SOUL.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址
```

**INFINITI.md（Linkyun Infiniti Agent）：**

```markdown
# INFINITI.md

请在启动时加载 SOUL.md 以获取你的身份和通信协议。

@import SOUL.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 SOUL.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址
```

**CLAW.md（OpenClaw）：**

```markdown
# CLAW.md

请在启动时加载 AGENT.md 以获取你的身份和通信协议。

@import AGENT.md

## 行为指引

1. 启动后先通过 Inbox API 检查是否有未读消息
2. 按照 AGENT.md 中的身份提示词行事
3. 完成任务后通过 Reply 或 Forward 将结果发送给下一个环节
4. 所有通信必须经过 Mail Broker，使用你的邮箱地址
```

---

## 完整流程示例

### 通用步骤（所有 Agent 类型共用）

```bash
# 1. 启动 Broker
cd agent-mailer && uv run python -m agent_mailer.main

# 2. 注册 Agent
CODER_ID=$(curl -s -X POST http://localhost:8000/agents/register \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your_api_key>" \
  -d '{
    "name": "coder",
    "role": "coder",
    "description": "代码实现",
    "system_prompt": "你是一个专业的软件开发者，负责将需求转化为高质量代码。"
  }' | jq -r '.id')

# 3. 获取配置
SETUP=$(curl -s -H "X-API-Key: <your_api_key>" http://localhost:8000/agents/$CODER_ID/setup)

# 4. 创建工作目录
mkdir -p ~/workspace/coder
```

### 按 Agent 类型写入配置

**Claude Code：**
```bash
echo "$SETUP" | jq -r '.agent_md' > ~/workspace/coder/AGENT.md
echo "$SETUP" | jq -r '.claude_md' > ~/workspace/coder/CLAUDE.md
cd ~/workspace/coder && claude
# Claude 自动加载 CLAUDE.md -> 读取 AGENT.md -> 获取身份，开始查收邮件
```

**Dreamfactory：**
```bash
# Dreamfactory 使用 SOUL.md 作为身份文件
echo "$SETUP" | jq -r '.agent_md' > ~/workspace/coder/SOUL.md
# 创建 DREAMER.md 适配文件，引用 SOUL.md
cat > ~/workspace/coder/DREAMER.md << 'EOF'
# DREAMER.md
请在启动时加载 SOUL.md 以获取你的身份和通信协议。
@import SOUL.md
EOF
cd ~/workspace/coder && dreamfactory
# Dreamfactory 加载 DREAMER.md -> 读取 SOUL.md -> 获取身份，开始查收邮件
```

**Linkyun Infiniti Agent：**
```bash
# Infiniti 使用 SOUL.md 作为身份文件
echo "$SETUP" | jq -r '.agent_md' > ~/workspace/coder/SOUL.md
# 使用接口返回的 infiniti_md，或手动创建 INFINITI.md 适配文件
echo "$SETUP" | jq -r '.infiniti_md' > ~/workspace/coder/INFINITI.md
cd ~/workspace/coder && infiniti
# Infiniti 加载 INFINITI.md -> 读取 SOUL.md -> 获取身份，开始查收邮件
```

**OpenClaw：**
```bash
echo "$SETUP" | jq -r '.agent_md' > ~/workspace/coder/AGENT.md
# 创建 CLAW.md 适配文件，引用 AGENT.md
cat > ~/workspace/coder/CLAW.md << 'EOF'
# CLAW.md
请在启动时加载 AGENT.md 以获取你的身份和通信协议。
@import AGENT.md
EOF
cd ~/workspace/coder && openclaw
# OpenClaw 加载 CLAW.md -> 读取 AGENT.md -> 获取身份，开始查收邮件
```

---

## 设计要点

- **`system_prompt` 是注册时的必填项**：它定义了 Agent 的核心行为，不同的身份提示词让同一个底层 LLM 扮演不同角色
- **AGENT.md 是通用身份格式**：不绑定任何特定 Agent 实现，任何能读取 Markdown 的系统都可以解析
- **适配文件是桥接层**：每种 Agent 类型都有自己的适配文件（CLAUDE.md / DREAMER.md / INFINITI.md / CLAW.md / .cursorrules），通过引用身份文件实现身份注入
- **身份文件命名约定**：大多数 Agent 类型使用 `AGENT.md` 作为身份文件；Dreamfactory 和 Linkyun Infiniti Agent 使用 `SOUL.md`（内容格式相同，仅文件名不同）
- **一目录一身份**：不同工作目录对应不同 Agent 身份，同一个 Agent 在不同目录下自动切换角色
- **Agent 类型无关**：Broker 不感知 Agent 的具体类型，注册和通信协议对所有类型一致
