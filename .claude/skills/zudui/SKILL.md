---
name: zudui
description: Bootstrap a multi-agent team for the Agent Mailer Protocol via fully conversational setup. In claude code or codex chat, asks the user what agents they want, drafts system_prompts, confirms, then writes team.yaml and runs `agent-mailer up-team` to register agents and generate launcher scripts. Idempotent — re-running detects an existing team.yaml and only refreshes what's needed. The skill never launches terminals; that's start-team.sh's job. Use when the user invokes /zudui or 组队 / 开工 to bring up a team. Pairs with shangban (上班) and xiaban (下班) per agent.
---

# 组队 — Bootstrap an Agent Team via Chat

Pure-conversational setup that produces a `team.yaml` and hands the heavy lifting to the `agent-mailer up-team` CLI. The skill collects info and confirms; the CLI registers the agents on the broker, writes `agents/<name>/AGENT.md`+`.env`, and generates `start-team.sh`/`stop-team.sh`. Once setup is done, the user runs `./start-team.sh`.

Pairs with `shangban` (上班) per pane and `xiaban` (下班) per pane.

## Phase 1 — Pre-flight (silent if OK)

1. `command -v agent-mailer` — fail with install hint (`brew install uv && uv tool install agent-mailer` or whatever applies) if missing.
2. Broker URL: `${AMP_BROKER_URL:-http://127.0.0.1:9800}`. Smoke test `curl -fsS $BROKER_URL/health`. If unreachable: hint to start broker (`./run.sh` in the agent-mailer repo, or check the public URL).
3. Mother dir = current `pwd`. Mention it in the next question so the user can abort if wrong.

(tmux is NOT a prereq — `start-team.sh` errors out clearly if it's missing.)

## Phase 2 — Ensure logged in

Check `~/.agent-mailer/credentials.json` for an entry matching `$BROKER_URL`. If present, skip.

Otherwise ask once:

> 还没登录到 `$BROKER_URL`。给我用户名 + 密码，我用 `agent-mailer login` 登录一次（⚠️ 密码会出现在本次对话日志里）。

Run:
```bash
AMP_PASSWORD="$P" agent-mailer login --broker-url "$BROKER_URL" --username "$U"
```

`AMP_PASSWORD` env var keeps the password out of `ps` output. On 401: `用户名/密码错误，重试或换账号`. Max 2 retries then abort.

## Phase 3 — Gather team (conversational)

### Step 1 — Team prefix (mandatory)

Same broker account often hosts multiple teams from different mother dirs. Naked role names (`planner`, `coder`) collide on the second team — broker returns 409 because the user already owns an agent with that name. So **every agent name must be prefixed `<team>_<role>`**, and the agent subdir uses the same prefixed name (`agents/<prefix>_<role>/AGENT.md`).

Derive a default prefix from mother dir basename, stripping common noise (`agents_`, `agent_`, `_agents`, trailing `_team`). E.g. `agents_agentemail` → suggest `agentemail` and the shorter `email`. Show 1–2 candidates plus "自己起一个", and ask:

> 同账号多 team 必须用前缀区分（否则名字会跟之前的 team 撞车 409）。每个 agent 注册成 `<前缀>_<角色>`，目录也用同名。
> 候选: `<a>` / `<b>` / 自己起一个 (`[a-z0-9]{2,16}`)

Lowercase the answer; coerce to `[a-z0-9]{2,16}`.

### Step 2 — Team composition

Ask:

> 现在说说你要哪些角色 — 名字 + 各自负责什么:
> · `default` → 标准 4 角色 (planner / coder / reviewer / runner)
> · 自由列出: `planner 拆需求 / coder 写码 / reviewer 审 / runner 跑`
> · 一行一个角色，带详细描述
> · 1-9 个 agent 都行
> · 想用 codex 跑某个角色就备注 `(codex)`，否则默认 claude

Parse the reply (raw role suffixes; the skill prepends `<prefix>_` automatically):

- `default` / `标准` / `默认` / `常规` → use the default 4-role table verbatim.
- Free-form → extract `(role_suffix, runtime, short-description)` triples. Lowercase suffixes; coerce to `[a-z0-9._-]{1,30}`. Final agent name = `<prefix>_<suffix>`. Chinese-only suffixes → ask for English alias.
- For each agent generate `system_prompt` from description. **Always reference downstream agents by their full prefixed name** (e.g. "forward 给 `<prefix>_coder`", not bare `coder`). **Always include an explicit action edge** ("完成后 reply / forward 给 X") — otherwise shangban's PM-default decision rules misfire on non-PM roles.

### Default 4-role table

(`<P>` is the chosen prefix; runtime defaults to `claude`.)

| name | role | description | system_prompt |
|---|---|---|---|
| `<P>_planner`  | planner  | 需求拆解与架构设计 | 你是需求分析与架构设计专家。收到自然语言需求后，拆解为清晰的技术规格（模块划分、接口设计、验收标准），通过 forward 把任务给 `<P>_coder`，reply 通知发起人状态。 |
| `<P>_coder`    | coder    | 代码实现 | 你是软件开发者。收到技术规格后编写代码并附测试，完成后 reply 给 `<P>_reviewer` 申请审查。**不要 forward 出去**——边界是把成品交给 reviewer。 |
| `<P>_reviewer` | reviewer | 代码审查 | 你是代码审查专家。审查正确性、安全性、风格。问题 reply 给 `<P>_coder` 附具体修改意见；通过 reply 给 `<P>_planner` 并 forward 给 `<P>_runner` 验证。 |
| `<P>_runner`   | runner   | 执行验证与部署 | 你是执行验证专家。运行测试、部署 staging、做 smoke check。完成后 reply 给 `<P>_planner` 汇报最终状态。 |

### Heuristics for generated prompts (when not default)

Match on the role suffix (the part after the prefix), not the full name:

- suffix `planner|pm|产品` → PM-style: 拆解 → forward 下游
- suffix `coder|dev|开发|前端|后端` → 实现型: reply 给审查者，**不 forward**
- suffix `reviewer|qa|审查|测试` → 审查型: 问题 reply、通过 forward 下游
- suffix `runner|ops|运维|部署` → 执行型: 跑/部署/汇报
- 其他 → 用户描述 + 默认尾巴 "完成后 reply 给发起人，有疑问先 reply 澄清"

### Confirmation

Show compact draft, ask once:
```
前缀: <P>
broker: <URL>
我理解为:
  1. <P>_planner   (claude) — 需求拆解 → forward <P>_coder
  2. <P>_coder     (claude) — 写码+测试 → reply <P>_reviewer
  3. <P>_runner    (codex)  — 跑测试 → reply <P>_planner
  ...
确认在 broker 注册以上 N 个 agent? (yes / 改某条 / no)
```

- yes / 好 / ok → Phase 4
- 用户改某条 → 调整后再 show + 再确认
- no → 中止，不写任何文件

## Phase 4 — Write team.yaml + run up-team

1. Compose `<mother>/team.yaml`:

   ```yaml
   team: <P>
   broker_url: <BROKER_URL>
   defaults:
     runtime: claude
   agents:
     - name: <P>_planner
       role: planner
       runtime: claude
       system_prompt: |
         你是需求分析与架构设计专家...
     - name: <P>_coder
       role: coder
       system_prompt: |
         ...
     # etc.
   ```

   Notes:
   - `name` is fully prefixed.
   - Per-agent `runtime` only emitted when it differs from `defaults.runtime` (cleaner yaml).
   - System prompts are the multi-line block style (`|`).

2. Run:
   ```bash
   agent-mailer up-team "<mother>/team.yaml"
   ```

   `up-team` does the rest:
   - `POST /admin/teams/bootstrap` (one transaction → N agents registered atomically)
   - Writes `agents/<name>/{AGENT.md, .env}` (`.env` mode 0600)
   - Generates `start-team.sh` and `stop-team.sh` (chmod +x)
   - Generates `.agent-mailer/codex-ticks.json` if any codex agents exist
   - Appends `agents/`, `start-team.sh`, `stop-team.sh`, `.agent-mailer/` to `.gitignore` (idempotent)

3. On `up-team` failure, surface stderr verbatim. Common cases:
   - **409 team name already exists** → user has run zudui before with this prefix. Tell them: either pick a new prefix in Phase 3, or `curl -X DELETE $BROKER_URL/admin/teams/<id>` (looked up via `GET /admin/teams`) to reset.
   - **session expired** → re-run Phase 2.

## Phase 5 — Claude Code scaffold (only if any claude agent exists)

Without this, every claude pane hits permission prompts on its first `curl` to the broker, on every `CronList`/`CronCreate`, etc. Trust acceptance and bypass dismissal are handled by the generated `start-team.sh` itself; this step adds the defense-in-depth allowlist.

Write `<mother>/.claude/settings.json` (NOT `.local.json` — these allows are team-scaffold, not per-user, so they should travel with the team):

```json
{
  "permissions": {
    "allow": [
      "Bash(curl:*)",
      "Bash(jq:*)",
      "CronList",
      "CronCreate",
      "CronDelete",
      "ToolSearch"
    ]
  }
}
```

If `<mother>/.claude/settings.json` already exists: merge — add any missing entries to `permissions.allow`, preserve everything else (hooks, env, model, other allow rules). Don't overwrite the file.

These permissions apply to claude sessions started anywhere under `<mother>/` because Claude Code walks up the tree for project settings.

## Phase 6 — Wrap up

Print:
```
组队完成 ✓
  · team.yaml 已写入 <mother>/team.yaml (可 commit、可复制到别的项目复用)
  · N 个 agent 已注册
  · agents/<name>/{AGENT.md,.env} 已落盘 (.env mode 0600)
  · start-team.sh / stop-team.sh 已生成
  · 自动追加 .gitignore: agents/, start-team.sh, stop-team.sh, .agent-mailer/

启动: ./start-team.sh
       (创建命名 tmux 会话，幂等 attach)
       claude pane 自动跑 `claude --dangerously-skip-permissions "上班"`
       codex pane 自动跑 `codex "查收..."`，外加后台 codex-tick 守护进程

收工: ./stop-team.sh
       (杀 tmux 会话 + 停 codex-tick 守护进程)
```

## Boundaries

- Skill never launches tmux / terminals — that's `start-team.sh`'s job.
- Never echo password back to the user; pass it via `AMP_PASSWORD` env var, never as a `--password` flag (visible in `ps`).
- Never silently use defaults — always echo the parsed/generated team back, require explicit confirmation.
- Never register naked role names (`planner`, `coder`); a team prefix is mandatory in Phase 3 Step 1.
- Generated `system_prompt`s must reference downstream agents by their **full prefixed name** (e.g. `<prefix>_coder`), never bare role names — otherwise routing crosses team boundaries.
- If a pasted answer in Phase 3 confirmation is non-affirmative, do not write any file.
- Re-running zudui with an existing `<mother>/team.yaml`: ask whether to overwrite. If user agrees, the broker call still hits 409 on the team name unless the team was deleted first; surface that clearly so the user can either pick a new prefix or delete the old team.
- The skill's job ends after Phase 6. The launcher (`start-team.sh`) handles workspace-trust pre-acceptance and bypass-permissions dismissal at run time.
