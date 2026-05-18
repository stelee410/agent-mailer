# `agent-mailer team init` — multi-agent team bootstrap

Provisions a 4-role agent team (`pm`, `dev`, `reviewer`, `support`) on
`amp.linkyun.co` and scaffolds per-role workdirs so each role can be launched
with `agent-mailer watch` (i.e. the runtime only spawns when a new mail
arrives — no idle agents).

Supersedes the standalone `amp-team` Node package as of v0.1.x.

## Quick start

```bash
mkdir my-team && cd my-team
agent-mailer team init
```

The interactive wizard asks for:

1. Team name (default: directory basename, slugified).
2. Framework for each role:
   - `Claude Code` ✓
   - `Codex` ✓
   - `Infiniti-Agent` ✓ (requires `infiniti-agent` CLI on `$PATH`)
   - `OpenClaw` / `Dreamfactory` — listed as "即将支持"; selecting one
     triggers a clear error and re-prompts (no silent fallback).
3. amp.linkyun.co username + password (password masked, 3 retries on
   bad credentials).

## `permission_mode` semantics across runtimes

`permission_mode` (set in each role's `.agent-mailer/config.toml`) maps to
runtime-specific flags. The same label has different reach depending on
runtime — pick deliberately:

| `permission_mode`             | claude                                                          | codex                                                          | infiniti                                  |
|-------------------------------|-----------------------------------------------------------------|----------------------------------------------------------------|-------------------------------------------|
| `bypassPermissions` (default) | `--dangerously-skip-permissions` (no approval gate, fully auto) | `--dangerously-bypass-approvals-and-sandbox` (raw shell, no sandbox) | runtime ignores                            |
| `acceptEdits`                 | `--permission-mode acceptEdits` — file edits without prompts; no shell | `--sandbox workspace-write` — file edits **and** sandboxed shell | runtime ignores; uses its own internal defaults |
| `plan`                        | `--permission-mode plan` (plan-only, read-only)                 | `--sandbox read-only --ask-for-approval never`                 | runtime ignores                            |

Three non-obvious points:

- **`bypassPermissions` for claude maps to `--dangerously-skip-permissions`**,
  not `--permission-mode bypassPermissions`. They mean the same thing in
  claude-code's docs, but only the `--dangerously-skip-permissions` form
  actually disables per-tool approval prompts under headless `-p` mode.
  This is why it's the default for `team init` — auto-watch needs zero
  approval gates.
- **Codex's `acceptEdits` includes sandboxed shell**, while claude's
  `acceptEdits` does **not**. If you want strict no-shell behaviour across
  both, choose `plan`.
- **Infiniti ignores `permission_mode` entirely** today (the
  `infiniti-agent cli` surface has no equivalent flag). The field is still
  written into config.toml for audit symmetry but has no runtime effect.

## What it writes

```
my-team/
├── .amp-team/
│   └── team.json                  # team metadata, partial flag, agent list
├── pm/
│   ├── .agent-mailer/
│   │   └── config.toml            # full Config (agent_id, api_key, runtime, …)
│   ├── .claude/
│   │   └── settings.json          # broker allowlist (claude runtime only)
│   ├── AGENT.md                   # broker-supplied identity (or SOUL.md if Infiniti)
│   └── CLAUDE.md                  # runtime adapter (or INFINITI.md if Infiniti)
├── dev/ … (same shape)
├── reviewer/ … (same shape)
├── support/ … (same shape)
├── start-pm.sh / start-pm.cmd     # cd pm/ && exec agent-mailer watch
├── start-dev.sh / start-dev.cmd
├── start-reviewer.sh / start-reviewer.cmd
└── start-support.sh / start-support.cmd
```

Each role workdir is a full `agent-mailer watch` workdir — `doctor`,
`logs`, `sessions` all work inside it.

### Why `.claude/settings.json` (claude runtime only)

The default `bypassPermissions` mode already disables every per-tool
approval prompt via `--dangerously-skip-permissions`, so for the default
config the allowlist is **defence-in-depth** rather than load-bearing.

It becomes load-bearing the moment a user picks a stricter
`permission_mode`: claude's `acceptEdits` auto-approves file edits but
**not Bash / network**, and `plan` is read-only. In a headless `-p`
invocation there is no human to type "y", so without the allowlist every
`curl https://amp.linkyun.co/...` hangs on "This command requires
approval" and the watcher burns the full timeout for ~zero output.
`team init` ships a surgical allowlist so the downgrade path stays
functional:

```json
{
  "permissions": {
    "allow": [
      "Bash(curl:*amp.linkyun.co*)",
      "Bash(agent-mailer:*)",
      "WebFetch(domain:amp.linkyun.co)"
    ]
  }
}
```

The three entries cover the two distinct paths claude can take to reach the
broker: `Bash(curl:…)` for shell-driven `curl https://amp.linkyun.co/...`,
`Bash(agent-mailer:*)` for the wrapped CLI, and `WebFetch(domain:…)` for
claude's built-in `WebFetch` tool — the prompt templates use neutral verbs
(GET / POST / PATCH) and don't pin claude to curl, so either tool may be
picked at runtime.

This is intentionally narrow — `bypassPermissions` would solve the same
problem with much wider blast radius (any Bash). Codex and Infiniti roles
don't get this file: `codex_runner` already passes
`--ask-for-approval never`, and the `infiniti-agent cli` surface has no
approval gate at all.

### Migrating an existing workdir

If you scaffolded a team before this allowlist shipped, drop the file in
under each role directory:

```bash
for role in pm dev reviewer support; do
  mkdir -p "$role/.claude" && cat > "$role/.claude/settings.json" <<'EOF'
{"permissions":{"allow":["Bash(curl:*amp.linkyun.co*)","Bash(agent-mailer:*)","WebFetch(domain:amp.linkyun.co)"]}}
EOF
done
```

Re-run `agent-mailer team init` in a fresh directory if you'd rather start
clean.

## Failure handling

If the broker rejects a create call, `team init` writes
`.amp-team/team.json` with `partial: true` and returns exit code 2.

If `GET /agents/{id}/setup` fails (e.g. transient 5xx, expired token), the
api_key has already been persisted to `<role>/.agent-mailer/config.toml`
with a `partial_setup_pending` marker file next to it. **Without this,**
the broker-side one-shot `api_key_plaintext` would be irretrievable. The
user can fix the network issue and re-run setup; the credentials are
already on disk.

This is the same P1-3 invariant the v0.1.1 amp-team port introduced; the
Python version preserves it.

## Manual end-to-end verification (PM)

The automated pytest suite stubs the broker via `httpx.MockTransport`.
For a real-broker smoke test, in a sandbox account:

```bash
# 1. Clean workspace (must be empty bar .git / IDE files).
mkdir /tmp/team-e2e-$(date +%s) && cd /tmp/team-e2e-$(date +%s)

# 2. Run init pointing at the real broker.
agent-mailer team init --broker-url https://amp.linkyun.co

#    Pick: pm=claude, dev=codex, reviewer=claude, support=infiniti.
#    Enter the test account credentials when prompted.

# 3. Inspect outputs.
cat pm/.agent-mailer/config.toml          # 0600, runtime="claude", api_key set
ls pm/                                     # AGENT.md + CLAUDE.md + .agent-mailer/
ls support/                                # SOUL.md + INFINITI.md + .agent-mailer/
cat .amp-team/team.json                    # partial: false, 4 agents listed

# 4. Smoke-launch one role.
./start-pm.sh                              # should hit the watch loop, poll inbox

# 5. Cleanup: delete the 4 test agents from broker (UI or API).
#    Test agents are named:  <team>-pm, <team>-dev, <team>-reviewer, <team>-support
```

Recommended cleanup script (PM-side, requires the user token). The broker's
`/users/me/agents/{id}` route expects an agent UUID — agent names won't
resolve — so use the two-step list-then-delete flow:

```bash
TEAM=<team-slug>; TOKEN=<bearer>

# 1. List your agents, keep only the ones whose name starts with the team slug.
IDS=$(curl -s -H "Authorization: Bearer $TOKEN" \
        https://amp.linkyun.co/users/me/agents \
      | python3 -c "import sys, json; print('\n'.join(
          a['id'] for a in json.load(sys.stdin) if a['name'].startswith(f'$TEAM-')))")

# 2. Delete each one by ID.
for ID in $IDS; do
  curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \
    "https://amp.linkyun.co/users/me/agents/$ID"
done
```

`jq` works equally well in place of the inline python (`jq -r '.[] | select(.name | startswith($t+"-")) | .id' --arg t "$TEAM"`).

## Migration from the legacy `amp-team` Node CLI

A standalone `amp-team` npm package shipped briefly with the v0.1.x line
and was retired in favour of this Python subcommand. Differences:

- Old: `amp-team` (Node, generated `start-<role>.sh` that directly execed
  `claude` / `infiniti`).
- New: `agent-mailer team init` (Python, generates `start-<role>.sh` that
  execs `agent-mailer watch`, which polls the broker and spawns the
  runtime only when a new message arrives).

No data migration is needed if you don't have an existing team scaffolded.
For an existing amp-team workdir, the simplest path is to delete the old
files and re-run `agent-mailer team init` in a fresh directory.
