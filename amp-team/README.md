# amp-team — DEPRECATED

> **Deprecated as of 2026-05-18.** Use `agent-mailer team init` from the
> [agent_mailer_cli](../src/agent_mailer_cli) Python package instead. The
> Python port supports the same flow plus:
>
> - **Watch-mode launchers**: generated `start-<role>.sh` runs
>   `agent-mailer watch` so the runtime only spawns when a new email
>   arrives (matches what real usage wanted).
> - **All three runtimes**: `claude` / `codex` / `infiniti` are all
>   selectable from the menu (this Node version only supported claude +
>   infiniti and hard-failed codex selections).
> - **Tighter integration**: each role dir is a normal
>   `.agent-mailer/config.toml` workdir, so `agent-mailer doctor`, `logs`,
>   `sessions`, etc. all work out of the box.
>
> Source is preserved here for reference but receives no further updates.

One-shot CLI that registers a 4-role agent team (pm / dev / reviewer / support)
on `amp.linkyun.co` and scaffolds local workdirs ready to launch.

## Install

```bash
npm install -g .                # from a checkout
# or, once published: npm install -g amp-team
```

Requires Node.js ≥ 18 (uses built-in `fetch`).

## Usage

In an **empty** directory:

```bash
amp-team
```

The interactive flow asks for:

- a team name (defaults to the directory basename, slugified to a broker-legal local-part)
- your `amp.linkyun.co` username and password (password masked)
- the agent framework for each role:
  - `Claude Code` ✓
  - `Infiniti-Agent` ✓
  - `Codex` / `OpenClaw` / `Dreamfactory` — listed as "即将支持"; selecting one
    shows a clear error and re-prompts the role (no silent fallback to Claude).

It then:

1. `POST /users/login` to get a session token
2. `POST /users/me/agents` four times — one per role
3. `GET /agents/<id>/setup` to fetch the official `AGENT.md` / `CLAUDE.md` / `INFINITI.md` templates per agent
4. Materializes each role's workdir:
   - `<role>/AGENT.md` (or `SOUL.md` for Infiniti)
   - `<role>/CLAUDE.md` (or `INFINITI.md` for Infiniti)
   - `<role>/.amp-team/credentials.json` — chmod 0600 on POSIX
   - `<role>/.amp-team/inbox.js` — standalone TUI inbox poller (no amp-team runtime deps)
5. Writes `start-<role>.sh` + `start-<role>.cmd` launchers in the team root
6. Persists `.amp-team/team.json` with the agent ID list (and a `partial: true` marker if any step failed)

## Run

```bash
./start-pm.sh                              # launch Claude / Infiniti in pm/
node pm/.amp-team/inbox.js                    # live inbox (2-second refresh, in-place rewrite)
```

The inbox viewer rewrites the screen every poll instead of scrolling, so it
fits in a single pane next to the agent terminal.

## Environment overrides

| var | purpose |
|---|---|
| `AMP_TEAM_BROKER_URL` | default broker URL shown in the prompt (default `https://amp.linkyun.co`) |
| `AMP_TEAM_DEBUG` | print error stack traces |

## Layout produced

```
.
├── .amp-team/team.json
├── pm/AGENT.md
├── pm/CLAUDE.md
├── pm/.amp-team/credentials.json     # 0600
├── pm/.amp-team/inbox.js
├── dev/ … (same shape)
├── reviewer/ … (same shape)
├── support/ … (same shape, SOUL.md + INFINITI.md if Infiniti chosen)
├── start-pm.sh / start-pm.cmd
├── start-dev.sh / start-dev.cmd
├── start-reviewer.sh / start-reviewer.cmd
└── start-support.sh / start-support.cmd
```

## Tests

```bash
npm test
```

The smoke suite covers:

- slug + empty-dir + script generation
- end-to-end init under a stubbed broker (no network), verifying file layout, secret-file permissions, Bearer/X-API-Key header routing, and SOUL.md/INFINITI.md vs AGENT.md/CLAUDE.md branching
- partial-failure flow: the `.amp-team/team.json` `partial: true` marker is written when broker rejects a creation request mid-team
