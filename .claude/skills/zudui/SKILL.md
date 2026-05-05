---
name: zudui
description: Bootstrap a multi-agent team for the Agent Mailer Protocol via fully conversational setup. In claude code or codex chat, asks the user what agents they want, drafts system_prompts, confirms, then either uses an existing API key or logs in to create a fresh one. Registers each agent on the broker, writes per-role AGENT.md, drops a smart start-team.sh launcher (tmux > iTerm2 > manual fallback), saves credentials to a 0600 .env. The skill never launches terminals — that's start-team.sh's job. Use when the user invokes /zudui or 组队 / 开工 to bring up a team. Pairs with shangban (上班) and xiaban (下班) per agent. Idempotent: re-running detects existing AGENT.md and refreshes only what's needed.
---

# 组队 — Bootstrap an Agent Team via Chat

Pure-conversational setup for the Agent Mailer Protocol. The skill collects info, registers agents, writes files. **It never launches terminals itself** — once setup is done, the user runs `./start-team.sh` (auto-detects tmux / iTerm2 / manual).

Pairs with `shangban` (上班) per pane and `xiaban` (下班) per pane.

## Phase 1 — Pre-flight (silent if OK)

1. `command -v claude` — fail with install hint if missing.
2. Determine broker URL: `${AMP_BROKER_URL:-http://127.0.0.1:9800}`. Smoke test `curl -fsS $BROKER_URL/health`. Fail with hint to start broker (e.g. `./run.sh` in agent-mailer repo, or check the public URL).
3. Mother directory = current `pwd`. Mention it in the next question so the user can abort if wrong.

(tmux is NOT a prereq — start-team.sh handles launcher detection at run time.)

## Phase 2 — Acquire API key

Resolve `AMP_API_KEY`:

1. **Env var `AMP_API_KEY`** set OR `<mother>/.env` contains `AMP_API_KEY=...` → validate via `curl -fsS -H "X-API-Key: $k" $BROKER_URL/agents`. 200 accept; 401 treat as missing.

2. Otherwise ask once:
   > 还没找到 API key。两种方式:
   > · 已有 key → 粘贴 `amk_` 开头的字符串
   > · 让我帮你建一个新 key → 给我用户名 + 密码 (⚠️ 密码会出现在本次对话日志里)

3. Branch by user reply:
   - Reply starts with `amk_` → treat as paste; validate via `GET /agents`; on 401 retry once then abort.
   - Otherwise treat reply as username; ask password next; then login + create:

   ```bash
   # Pass JSON via stdin (heredoc) so the password doesn't appear in `ps` output.
   TOKEN=$(curl -fsS -X POST "$BROKER_URL/users/login" \
     -H "Content-Type: application/json" \
     --data @- <<EOF | jq -r '.token'
   {"username":"$U","password":"$P"}
   EOF
   )
   [[ -n "$TOKEN" && "$TOKEN" != "null" ]] || abort with "登录失败"

   raw_key=$(curl -fsS -X POST "$BROKER_URL/users/api-keys" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"name\":\"zudui-$(date -u +%Y%m%dT%H%M%SZ)\"}" | jq -r '.raw_key')
   ```
   - 401 on login → "用户名/密码错误。重试或换粘贴方式。" Max 2 retries then abort.
   - Broker returns plaintext key once — capture immediately.

4. Persist:
   ```bash
   umask 077
   cat > "<mother>/.env" <<EOF
   AMP_API_KEY=$raw_key
   AMP_BROKER_URL=$BROKER_URL
   EOF
   chmod 600 "<mother>/.env"
   ```
   Tell user: "✓ key 已存到 `<mother>/.env` (0600,已 gitignore)。"

## Phase 3 — Gather team (conversational)

### Step 1 — Team prefix (mandatory)

Same broker account often hosts multiple teams from different mother dirs. Naked role names (`planner`, `coder`) collide on the second team — broker returns 409 because the user already owns an agent with that name. So **every agent name must be prefixed `<team>_<role>`**, and the on-disk subdir uses the same prefixed name (`<mother>/<prefix>_<role>/AGENT.md`) so the launcher's auto-discovery still works.

Derive a default prefix from mother dir basename, stripping common noise (`agents_`, `agent_`, `_agents`, trailing `_team`, etc.). E.g. `agents_agentemail` → suggest `agentemail` and the shorter `email`. Show 1–2 candidates plus "自己起一个", and ask:

> 同账号多 team 必须用前缀区分 (否则名字会跟之前的 team 撞车 409)。每个 agent 注册成 `<前缀>_<角色>`,目录也用同名。
> 候选: `<a>` / `<b>` / 自己起一个 (`[a-z0-9]{2,16}`)

Lowercase the answer, coerce to `[a-z0-9]{2,16}`. Validate by `GET /agents` for the current user — if any existing agent name starts with `<prefix>_` AND the matching subdir does NOT yet exist in `<mother>`, that prefix is taken by a foreign team; reject and ask again. (Existing same-prefix agents whose subdirs DO already exist in `<mother>` are fine — that's the idempotent rerun case.)

### Step 2 — Team composition

Ask:
> 现在说说你要哪些角色 — 名字 + 各自负责什么:
> · `default` → 标准 4 角色 (planner / coder / reviewer / runner),会注册成 `<前缀>_planner` 等
> · 自由列出: `planner 拆需求 / coder 写码 / reviewer 审 / runner 跑` (前缀自动加)
> · 一行一个角色,带详细描述
> · 1-9 个 agent 都行

Parse user reply (user types raw role suffixes; skill prepends `<prefix>_` automatically):

- `default` / `标准` / `默认` / `常规` → use the default 4-role table verbatim.
- Free-form → extract `(role_suffix, short-description)` pairs. Lowercase suffixes; coerce to `[a-z0-9._-]{1,30}`. Final agent name = `<prefix>_<suffix>`. Chinese-only suffixes → ask for English alias.
- For each agent generate `system_prompt` from description. **Always reference downstream agents by their full prefixed name** (e.g. "forward 给 `<prefix>_coder`", not bare `coder`) — otherwise the agent will dispatch to a foreign team's `coder` if one exists. **Always include an explicit action edge** ("完成后 reply / forward 给 X") — otherwise shangban's PM-default decision rules misfire on non-PM roles.

### Default 4-role table

(`<P>` is the chosen prefix.)

| name | role | description | system_prompt |
|---|---|---|---|
| `<P>_planner`  | planner  | 需求拆解与架构设计 | 你是需求分析与架构设计专家。收到自然语言需求后,拆解为清晰的技术规格(模块划分、接口设计、验收标准),通过 forward 把任务给 `<P>_coder`,reply 通知发起人状态。 |
| `<P>_coder`    | coder    | 代码实现 | 你是软件开发者。收到技术规格后编写代码并附测试,完成后 reply 给 `<P>_reviewer` 申请审查。**不要 forward 出去**——边界是把成品交给 reviewer。 |
| `<P>_reviewer` | reviewer | 代码审查 | 你是代码审查专家。审查正确性、安全性、风格。问题 reply 给 `<P>_coder` 附具体修改意见;通过 reply 给 `<P>_planner` 并 forward 给 `<P>_runner` 验证。 |
| `<P>_runner`   | runner   | 执行验证与部署 | 你是执行验证专家。运行测试、部署 staging、做 smoke check。完成后 reply 给 `<P>_planner` 汇报最终状态。 |

### Heuristics for generated prompts (when not default)

Match on the role suffix (the part after the prefix), not the full name:

- suffix `planner|pm|产品` → PM-style: 拆解 → forward 下游
- suffix `coder|dev|开发|前端|后端` → 实现型: reply 给审查者,**不 forward**
- suffix `reviewer|qa|审查|测试` → 审查型: 问题 reply、通过 forward 下游
- suffix `runner|ops|运维|部署` → 执行型: 跑/部署/汇报
- 其他 → 用户描述 + 默认尾巴 "完成后 reply 给发起人,有疑问先 reply 澄清"

### Confirmation

Show compact draft, ask once:
```
前缀: <P>
我理解为:
  1. <P>_planner   — 需求拆解 → forward <P>_coder
  2. <P>_coder     — 写码+测试 → reply <P>_reviewer
  ...
确认在 broker `<URL>` 注册以上 N 个 agent? (yes / 改某条 / no)
```
- yes / 好 / ok → Phase 4
- 用户改某条 → 调整后再 show + 再确认
- no → 中止,不写任何文件

## Phase 4 — Register

For each agent (in confirmed order). Throughout this phase, `<name>` means the fully prefixed `<prefix>_<role>` chosen in Phase 3 — never a bare role name.

1. **Idempotency**: if `<mother>/<name>/AGENT.md` already exists → skip; report `↻ <name> (existing)`.
2. Otherwise:
   - `mkdir -p <mother>/<name>`
   - `curl -fsS -X POST $BROKER_URL/agents/register -H "Content-Type: application/json" -H "X-API-Key: $AMP_API_KEY" -d '{"name":"<name>","role":"<role>","description":"<desc>","system_prompt":"<prompt>"}'`
   - 409 → `GET /agents`, find row with matching `name`+`role` of current user, reuse `id`+`address`. No clean match → surface conflict, skip this agent.
   - Capture `id` + `address` from response.
   - `curl -fsS $BROKER_URL/agents/<id>/setup -H "X-API-Key: $AMP_API_KEY"` → write the `agent_md` field to `<mother>/<name>/AGENT.md`.
3. Report `✓ <name> @ <address>`.

If any agent fails, finish the rest, summarize at the end so the user can re-run `/zudui` to fill gaps.

## Phase 5 — Drop launcher + .gitignore + permissions

`cp <skill_dir>/start-team.sh.template <mother>/start-team.sh && chmod +x <mother>/start-team.sh` — overwrite without asking. The script auto-discovers agents by scanning subdirs containing `AGENT.md`, so it adapts to any team size.

If `<mother>/.gitignore` does not exist, create it with:
```
*/AGENT.md
.env
```
Don't trample an existing `.gitignore`.

### `.claude/settings.json` (required — pre-allow broker calls)

Without this, every pane's claude session hits a permission prompt on its first `curl` to the broker, on every `CronList`/`CronCreate` call, etc. — N agents × M tool types = a wall of prompts the user has to click through individually per pane.

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

If `<mother>/.claude/settings.json` already exists, merge: add any missing entries to `permissions.allow`, preserve everything else (hooks, env, model, other allow rules). Don't overwrite the file.

These permissions apply to claude sessions started anywhere under `<mother>/` — covering every agent subdir — because Claude Code walks up the tree for project settings.

Note on scope: `Bash(curl:*)` and `Bash(jq:*)` are broad (any curl / any jq). That's fine here — agents are scaffolded for broker work and the trust boundary is "this directory hosts an AMP team". `settings.json` is a defense-in-depth fallback; the launcher itself uses `--dangerously-skip-permissions` to keep autonomous agents from deadlocking on prompts during arbitrary task work.

### Two startup dialogs — the launcher handles them, but the skill must scaffold for it

Every fresh `claude` boot in an agent subdir hits **two** sequential dialogs that an autonomous agent can't answer:

1. **"Trust this folder?"** — Claude Code shows this the first time it sees a directory. Stored as `projects[<path>].hasTrustDialogAccepted` in `~/.claude.json`. Pre-writing this field works (verified). The `--dangerously-skip-permissions` flag does NOT cover trust.
2. **"Bypass permissions mode?"** — `--dangerously-skip-permissions` triggers this warning every session. The acceptance is NOT persisted (verified by JSON diff before/after manual accept), so it re-fires on every restart. Old `skipDangerousModePermissionPrompt: true` setting in `~/.claude/settings.json` is ignored in current Claude Code.

The launcher template (`start-team.sh.template`) already does both:

- `pre_trust_dirs()` writes `hasTrustDialogAccepted: true` for the mother dir + each agent subdir into `~/.claude.json` before spawning panes.
- `dismiss_bypass_dialogs()` polls each tmux pane via `capture-pane`, and sends keystroke `2` (= "Yes, I accept") only on panes whose buffer contains "Yes, I accept", with per-pane deduplication so a stray digit never lands in claude's input.

If you ever rewrite the launcher, both behaviors must survive. Without `pre_trust_dirs`, every pane hangs on "Trust this folder?". Without `dismiss_bypass_dialogs`, every pane hangs on the bypass warning. The skill's job ends at Phase 5; the launcher's job during runtime is to clear these gates.

For iTerm/manual launchers, `pre_trust_dirs` runs but bypass-dismissal isn't automated (AppleScript injection is messier than tmux send-keys). The wrap-up message tells the user to press `2` once per window.

## Phase 6 — Wrap up

Print:
```
组队完成 ✓
  · N 个 agent 已注册,AGENT.md 已写入 <mother>/<name>/
  · API key 已存到 <mother>/.env (0600, gitignored)
  · 智能 launcher 已生成: ./start-team.sh
        - 启动时会预批准 workspace trust (写 ~/.claude.json)
        - 用 --dangerously-skip-permissions 跑 claude (autonomous agent 必须)
        - 自动按 "2" 通过 bypass-permissions 警告框
  · 防御性允许列表: <mother>/.claude/settings.json (curl/jq/Cron* allowlist)

启动: ./start-team.sh
       (自动检测 tmux > iTerm2 > 手动指引)
       强制某种: TEAM_LAUNCHER=tmux ./start-team.sh

每个分屏会自动 claude + 上班,各自轮询自己的邮箱。
全部下班: 各分屏输入「下班」(若 tmux: tmux kill-session -t agent-team)
```

## Boundaries

- Skill never launches tmux / terminals — that's start-team.sh.
- Never echo password back to the user, never put it in a visible bash command argument (use stdin/heredoc).
- Never silently use defaults — always echo parsed/generated team back, require explicit confirmation.
- Never register naked role names (`planner`, `coder`, …); a team prefix is mandatory in Phase 3 Step 1. Naked names collide on the second team in the same broker account.
- Generated `system_prompt`s must reference downstream agents by their **full prefixed name** (e.g. `<prefix>_coder`), never bare role names — otherwise routing crosses team boundaries.
- Never create a stub AGENT.md if registration fails.
- After capturing raw API key, immediately `chmod 600 <mother>/.env`.
- If pasted API key fails validation twice, abort cleanly.
- If user replies non-affirmative to confirmation, do not write any file.
- If mother dir contains unrelated files, mention them and ask before overwriting.
