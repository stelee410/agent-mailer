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

## What it writes

```
my-team/
├── .amp-team/
│   └── team.json                  # team metadata, partial flag, agent list
├── pm/
│   ├── .agent-mailer/
│   │   └── config.toml            # full Config (agent_id, api_key, runtime, …)
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

Recommended cleanup script (PM-side, requires the user token):

```bash
TEAM=<team-slug>; TOKEN=<bearer>
for role in pm dev reviewer support; do
  curl -s -X DELETE "https://amp.linkyun.co/users/me/agents/${TEAM}-${role}" \
    -H "Authorization: Bearer $TOKEN"
done
```

## Migration from `amp-team` (Node)

The standalone `amp-team` Node CLI (in `/amp-team/`) is deprecated. Drop
in this replacement:

- Old: `amp-team` (Node, generates `start-<role>.sh` that directly execs
  `claude` / `infiniti`).
- New: `agent-mailer team init` (Python, generates `start-<role>.sh` that
  execs `agent-mailer watch`, which polls the broker and spawns the
  runtime only when a new message arrives).

No data migration is needed if you don't have an existing team scaffolded.
For an existing amp-team workdir, the simplest path is to delete the old
files and re-run `agent-mailer team init` in a fresh directory.
