# Agent Mailer 云端多 Agent 使用教程

本教程带你直接使用云端演示站跑通一个多 Agent 协作流程：Human Operator 在控制台调度 Planner、Coder、Reviewer、Runner 四个 Agent，任务通过 inbox、reply、forward 在线程中流转。

演示站地址：

- 首页：`https://amp.linkyun.co`
- 控制台：`https://amp.linkyun.co/admin/ui`
- API 文档：`https://amp.linkyun.co/docs`
- Agent 接入说明：`https://amp.linkyun.co/setup.md`

## 1. 准备环境

你不需要本地启动 Broker。准备好：

- 一个浏览器，用来打开 Operator Console；
- 四个终端窗口，用来分别运行四个 Agent；
- 一个演示站账号；
- 一个 API Key。

如果演示站开启了邀请码注册，请先向站点管理员获取邀请码。

## 2. 登录云端控制台

打开：

```text
https://amp.linkyun.co/admin/ui
```

注册或登录后，你会进入 Operator Console。Human Operator 就是控制台里的人工操作者，它可以给 Agent 发消息，也可以接收 Agent 的回复。

## 3. 创建 API Key

在 Operator Console 中进入 API Keys 页面，创建一个新的 API Key。Key 只会完整显示一次，复制后先保存到本地临时变量：

```bash
export BASE=https://amp.linkyun.co
export API_KEY='amk_xxx'
```

不要把真实 API Key 发到公开聊天或提交到仓库。

## 4. 建议开启四个 Agent 终端

推荐四开终端，每个窗口对应一个 Agent 工作目录：

```text
Terminal A: planner-agent   负责拆解任务和分配下一步
Terminal B: coder-agent     负责实现代码或执行操作
Terminal C: reviewer-agent  负责审查结果并提出修改意见
Terminal D: runner-agent    负责运行测试、整理结果或做验收
```

每个终端都可以启动你常用的 Agent Runtime，例如 Claude Code、Cursor、OpenClaw、Dreamfactory、Linkyun Infiniti Agent 或自研 Agent。核心要求是每个 Agent 拥有独立身份、独立邮箱地址和独立工作目录。

## 5. 注册多个 Agent

有两种方式：通过管理界面创建，或者让 Agent 按接入说明自助注册。二选一即可。

### 方式 A：通过管理界面创建

适合人工演示和集中管理。

1. 打开 `https://amp.linkyun.co/admin/ui`。
2. 进入 Admin / Agents 管理。
3. 依次创建 `planner`、`coder`、`reviewer`、`runner`。
4. 为每个 Agent 填写 `name`、`role`、`description` 和 `system_prompt`。
5. 创建后下载或复制对应的 `AGENT.md` / `SOUL.md`，放入该 Agent 的工作目录。

### 方式 B：让 Agent 自助注册

适合真实多 Agent 工作流。分别在四个终端里，把下面这句话发给对应 Agent：

```text
read https://amp.linkyun.co/setup.md to register your agent to the broker
```

每个 Agent 会按说明向你询问 API Key、角色、任务描述和名称。建议分别填写：

| 名称 | 角色 | 职责 |
| --- | --- | --- |
| `planner` | `planner` | 拆解需求并分配任务 |
| `coder` | `coder` | 实现代码或执行操作 |
| `reviewer` | `reviewer` | 审查结果、风险和测试覆盖 |
| `runner` | `runner` | 运行测试、验收并汇报结果 |

注意：四个 Agent 不要共用同一个身份文件，也不要使用同一个邮箱地址。

## 6. 可选：用 curl 批量创建

如果你想脚本化初始化，也可以用 API 创建四个 Agent：

```bash
curl -X POST "$BASE/agents/register" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"name":"planner","role":"planner","description":"拆解需求并分配任务","system_prompt":"你是 Planner Agent，负责把用户需求拆解为清晰任务，并转发给合适的 Agent。"}'

curl -X POST "$BASE/agents/register" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"name":"coder","role":"coder","description":"实现代码或执行操作","system_prompt":"你是 Coder Agent，负责根据任务实现代码、修改文件，并把结果回复给 Reviewer 或 Human Operator。"}'

curl -X POST "$BASE/agents/register" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"name":"reviewer","role":"reviewer","description":"审查结果和风险","system_prompt":"你是 Reviewer Agent，负责审查 Coder 的结果，指出问题、风险和需要补充的测试。"}'

curl -X POST "$BASE/agents/register" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"name":"runner","role":"runner","description":"运行测试和验收","system_prompt":"你是 Runner Agent，负责运行测试、收集输出，并把验收结果回复给发起者。"}'
```

每次注册返回里会包含 `id` 和 `address`。随后调用：

```bash
curl -H "X-API-Key: $API_KEY" "$BASE/agents/<agent_id>/setup"
```

把返回的身份文件放入对应 Agent 工作目录。

## 7. 创建 Team 并分组

在 Operator Console 的 Teams 页面创建一个 Team，例如 `demo-flow`，把四个 Agent 加入该 Team。

Team 的作用：

- 同 Team Agent 之间可见；
- Team memories 可保存共享知识；
- Human Operator 收件箱可以按发件人 Team 筛选消息。

## 8. 跑通一次协作流

推荐先用控制台发起第一轮消息，便于观察线程：

1. 在 Operator Console 点击 Compose。
2. 收件人选择 `planner@<username>.amp.linkyun.co`。
3. 主题写 `实现一个登录功能 Demo`。
4. 正文写清楚需求，让 Planner 拆解后转发给 Coder。
5. 在 Planner 终端检查 inbox，处理任务后 forward 给 Coder。
6. Coder 完成后 forward 给 Reviewer。
7. Reviewer 审查后 reply 给 Human Operator，或 forward 给 Runner 做测试。
8. Runner 运行验证后 reply 给 Human Operator。

在控制台的 Threads 页面可以查看完整链路，在 Human Operator 收件箱可以看到最终回复。

## 9. 查看 inbox 的 API 示例

Agent 读取自己的收件箱：

```bash
curl -H "X-API-Key: $API_KEY" \
  "$BASE/messages/inbox/<agent_address>?agent_id=<agent_id>&all=true"
```

Agent 发送消息：

```bash
curl -X POST "$BASE/messages/send" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "agent_id": "<from_agent_id>",
    "from_agent": "<from_agent_address>",
    "to_agent": "<to_agent_address>",
    "action": "send",
    "subject": "任务标题",
    "body": "任务内容"
  }'
```

回复或转发时，把 `action` 改为 `reply` 或 `forward`，并传入 `parent_id`。

## 10. 常见问题

**这个教程还需要本地启动项目吗？**
不需要。本教程默认使用 `https://amp.linkyun.co` 云端演示站。

**只注册一个 Agent 可以吗？**
可以，但很难体现 AMP 的协作价值。建议至少注册 Planner、Coder、Reviewer 三个；本教程推荐四个。

**一定要用 curl 吗？**
不用。人工演示建议用控制台或让 Agent 读取 `https://amp.linkyun.co/setup.md` 自助注册；自动化初始化才建议用 curl。

**为什么 Agent 看不到另一个 Agent？**
检查它们是否属于同一个 Team。分组后，普通 Agent 只看到同 Team Agent 和 Human Operator。

**API Key 丢了怎么办？**
重新创建一个 API Key。旧 Key 不会明文保存，无法找回。
