import argparse
import asyncio
import getpass
import json
import os
import secrets
import shlex
import shutil
import string
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from agent_mailer.auth import hash_password, verify_password
from agent_mailer.config import DOMAIN
from agent_mailer.db import DB_PATH, get_db, init_db


INVITE_CODE_CHARS = string.ascii_letters + string.digits
INVITE_CODE_LENGTH = 8

DEFAULT_BROKER_URL = "http://localhost:9800"
DEFAULT_CREDENTIALS_PATH = Path.home() / ".agent-mailer" / "credentials.json"


async def _bootstrap_admin(args):
    db = await get_db(args.db)
    await init_db(db)

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        print("Error: Users already exist. bootstrap-admin is only for first-time setup.")
        await db.close()
        sys.exit(1)

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, args.username, hash_password(args.password), 1, now),
    )
    await db.commit()
    await db.close()
    print(f"Superadmin user '{args.username}' created successfully.")
    print(f"User ID: {user_id}")


async def _generate_invite_code(args):
    db = await get_db(args.db)
    await init_db(db)

    cursor = await db.execute(
        "SELECT * FROM users WHERE username = ?", (args.username,)
    )
    user = await cursor.fetchone()
    if not user:
        print(f"Error: User '{args.username}' not found.")
        await db.close()
        sys.exit(1)

    if not verify_password(args.password, user["password_hash"]):
        print("Error: Invalid password.")
        await db.close()
        sys.exit(1)

    if not user["is_superadmin"]:
        print("Error: Only superadmin users can generate invite codes.")
        await db.close()
        sys.exit(1)

    code = "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(INVITE_CODE_LENGTH))
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO invite_codes (code, created_by, created_at) VALUES (?, ?, ?)",
        (code, user["id"], now),
    )
    await db.commit()
    await db.close()
    print(f"Invite code: {code}")


async def _migrate_db(args):
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database file '{args.db}' not found.")
        sys.exit(1)

    # 1. Backup
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{args.db}.bak.{timestamp}"
    shutil.copy2(args.db, backup_path)
    print(f"Backup created: {backup_path}")

    db = await get_db(args.db)
    await init_db(db)

    # 2. Create or find admin user
    username = "admin"
    domain_suffix = f"@{username}.{DOMAIN}"

    cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
    admin_user = await cursor.fetchone()
    if admin_user:
        admin_id = admin_user["id"]
        print(f"Using existing admin user: {admin_id}")
    else:
        admin_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
            (admin_id, username, hash_password(args.password), 1, now),
        )
        print(f"Created admin user: {admin_id}")

    # 3. Associate orphan agents
    cursor = await db.execute(
        "UPDATE agents SET user_id = ? WHERE user_id IS NULL", (admin_id,)
    )
    agents_updated = cursor.rowcount
    print(f"Agents associated with admin: {agents_updated}")

    # 4. Update agent addresses: {name}@local → {name}@admin.amp.linkyun.co
    cursor = await db.execute(
        "SELECT id, name, address FROM agents WHERE address LIKE '%@local'"
    )
    agents_to_rename = await cursor.fetchall()
    msg_from_updated = 0
    msg_to_updated = 0
    for agent in agents_to_rename:
        old_addr = agent["address"]
        # Extract the part before @local
        local_part = old_addr.split("@")[0]
        new_addr = f"{local_part}{domain_suffix}"
        await db.execute("UPDATE agents SET address = ? WHERE id = ?", (new_addr, agent["id"]))
        # 5. Update messages
        c1 = await db.execute(
            "UPDATE messages SET from_agent = ? WHERE from_agent = ?",
            (new_addr, old_addr),
        )
        msg_from_updated += c1.rowcount
        c2 = await db.execute(
            "UPDATE messages SET to_agent = ? WHERE to_agent = ?",
            (new_addr, old_addr),
        )
        msg_to_updated += c2.rowcount

    await db.commit()
    await db.close()

    print(f"Addresses updated: {len(agents_to_rename)} agents")
    print(f"Messages updated: {msg_from_updated} from_agent, {msg_to_updated} to_agent")
    print("Migration complete.")


# --- Credentials store (used by login/logout/up-team) ---


def _credentials_path(args) -> Path:
    p = getattr(args, "credentials_path", None)
    return Path(p) if p else DEFAULT_CREDENTIALS_PATH


def _load_credentials_file(path: Path) -> dict:
    """Load the credentials file. Returns ``{}`` if missing or unreadable."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    data.setdefault("credentials", {})
    return data


def _save_credentials_file(path: Path, data: dict) -> None:
    """Atomic write with mode 0600 so the JWT is not world-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _normalize_broker_url(url: str) -> str:
    return url.rstrip("/")


def resolve_broker_url(args, creds_data: dict | None = None) -> str:
    """CLI flag wins; else most recently logged-in default; else ``http://localhost:9800``."""
    if getattr(args, "broker_url", None):
        return _normalize_broker_url(args.broker_url)
    if creds_data and creds_data.get("default_broker_url"):
        return _normalize_broker_url(creds_data["default_broker_url"])
    return DEFAULT_BROKER_URL


def load_session(args) -> tuple[str, dict]:
    """Return (broker_url, {username, token}) or raise SystemExit with a hint."""
    path = _credentials_path(args)
    data = _load_credentials_file(path)
    broker_url = resolve_broker_url(args, data)
    entry = data.get("credentials", {}).get(broker_url)
    if not entry or not entry.get("token"):
        print(
            f"Error: not logged in to {broker_url}. "
            "Run `agent-mailer login` first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return broker_url, entry


# --- login / logout ---


async def _login(args, *, client: httpx.AsyncClient | None = None):
    broker_url = _normalize_broker_url(args.broker_url or DEFAULT_BROKER_URL)
    username = args.username or input(f"Username for {broker_url}: ").strip()
    if not username:
        print("Error: username is required.", file=sys.stderr)
        sys.exit(1)
    # Password sources (in order): --password flag > AMP_PASSWORD env var > interactive
    # prompt. The env var path is what scripted callers (e.g. the zudui skill)
    # should use — it keeps the password out of `ps` output.
    password = args.password or os.environ.get("AMP_PASSWORD")
    if not password:
        password = getpass.getpass(f"Password for {username}: ")
    if not password:
        print("Error: password is required.", file=sys.stderr)
        sys.exit(1)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{broker_url}/users/login",
            json={"username": username, "password": password},
        )
    finally:
        if own_client:
            await client.aclose()

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"Error: login failed ({resp.status_code}): {detail}", file=sys.stderr)
        sys.exit(1)

    token = resp.json()["token"]
    path = _credentials_path(args)
    data = _load_credentials_file(path)
    data.setdefault("credentials", {})[broker_url] = {
        "username": username,
        "token": token,
    }
    data["default_broker_url"] = broker_url
    _save_credentials_file(path, data)
    print(f"Logged in to {broker_url} as {username}.")


async def _logout(args):
    path = _credentials_path(args)
    data = _load_credentials_file(path)
    if not data.get("credentials"):
        print("Not logged in to any broker.")
        return

    broker_url = (
        _normalize_broker_url(args.broker_url) if args.broker_url else None
    )
    creds = data["credentials"]
    if broker_url:
        if broker_url not in creds:
            print(f"Not logged in to {broker_url}.")
            return
        creds.pop(broker_url)
        if data.get("default_broker_url") == broker_url:
            data["default_broker_url"] = next(iter(creds), None)
        print(f"Logged out of {broker_url}.")
    else:
        creds.clear()
        data.pop("default_broker_url", None)
        print("Logged out of all brokers.")

    if not creds:
        path.unlink(missing_ok=True)
    else:
        _save_credentials_file(path, data)


# --- up-team ---


_VALID_RUNTIMES = ("claude", "codex")


def _validate_team_spec(data: Any) -> dict:
    """Normalize and validate a team.yaml dict. Raises ``ValueError`` on bad input."""
    if not isinstance(data, dict):
        raise ValueError("team.yaml must be a YAML object at the top level")

    name = data.get("team")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'team' is required and must be a non-empty string")

    description = data.get("description") or ""
    broker_url = data.get("broker_url")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("'defaults' must be a YAML object")
    default_runtime = defaults.get("runtime", "claude")
    if default_runtime not in _VALID_RUNTIMES:
        raise ValueError(
            f"defaults.runtime must be one of {_VALID_RUNTIMES}, got '{default_runtime}'"
        )

    raw_agents = data.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        raise ValueError("'agents' must be a non-empty list")

    agents = []
    for i, raw in enumerate(raw_agents):
        if not isinstance(raw, dict):
            raise ValueError(f"agents[{i}] must be a YAML object")
        a_name = raw.get("name")
        if not isinstance(a_name, str) or not a_name.strip():
            raise ValueError(f"agents[{i}].name is required")
        runtime = raw.get("runtime", default_runtime)
        if runtime not in _VALID_RUNTIMES:
            raise ValueError(
                f"agents[{i}].runtime must be one of {_VALID_RUNTIMES}, got '{runtime}'"
            )
        tags = raw.get("tags") or []
        if not isinstance(tags, list):
            raise ValueError(f"agents[{i}].tags must be a list")
        agents.append({
            "name": a_name.strip(),
            "address_local": raw.get("address_local"),
            "role": raw.get("role") or "",
            "description": raw.get("description") or "",
            "system_prompt": raw.get("system_prompt") or "",
            "tags": tags,
            "runtime": runtime,
        })

    return {
        "team": name.strip(),
        "description": description,
        "broker_url": broker_url,
        "agents": agents,
    }


def _resolve_codex_tick_bin() -> str:
    """Best-effort absolute path to ``agent-mailer-codex-tick``.

    Falls back to the bare command name if not found on PATH — the user
    can hand-edit ``start-team.sh`` if their install layout is unusual.
    """
    return shutil.which("agent-mailer-codex-tick") or "agent-mailer-codex-tick"


def _render_start_team_sh(team_name: str, agents: list[dict]) -> str:
    session = f"agent-mailer-{team_name}"
    has_codex = any(a["runtime"] == "codex" for a in agents)
    has_claude = any(a["runtime"] == "claude" for a in agents)
    daemon_bin = _resolve_codex_tick_bin() if has_codex else None

    lines = [
        "#!/usr/bin/env bash",
        "# Generated by `agent-mailer up-team`. Re-run up-team to regenerate.",
        "set -euo pipefail",
        "",
        f'SESSION={shlex.quote(session)}',
        'cd "$(dirname "$0")"',
        'PROJ_DIR="$(pwd)"',
        "",
        "if ! command -v tmux >/dev/null 2>&1; then",
        '  echo "Error: tmux is required (brew install tmux / apt install tmux)." >&2',
        "  exit 1",
        "fi",
        "",
        'if tmux has-session -t "$SESSION" 2>/dev/null; then',
        '  echo "Session $SESSION already exists — attaching."',
        '  exec tmux attach -t "$SESSION"',
        "fi",
        "",
    ]

    if has_claude:
        # Pre-write `hasTrustDialogAccepted: true` for each claude agent dir into
        # ~/.claude.json. Without this, every fresh `claude` boot in a new dir blocks
        # on "Trust this folder?" — which an autonomous agent can't answer. The
        # --dangerously-skip-permissions flag does NOT cover trust; trust is a
        # separate gate.
        claude_dirs = " ".join(
            shlex.quote(f"agents/{a['local']}") for a in agents if a["runtime"] == "claude"
        )
        lines += [
            "# Pre-accept Claude Code workspace trust for each agent dir.",
            'CLAUDE_JSON="$HOME/.claude.json"',
            f"CLAUDE_DIRS=({claude_dirs})",
            'if [ -f "$CLAUDE_JSON" ] && command -v python3 >/dev/null 2>&1; then',
            '  python3 - "$CLAUDE_JSON" "$PROJ_DIR" "${CLAUDE_DIRS[@]}" <<\'PY\'',
            "import json, sys",
            "cfg, parent, *subs = sys.argv[1:]",
            "with open(cfg) as f: data = json.load(f)",
            'projects = data.setdefault("projects", {})',
            "for path in [parent] + [f\"{parent}/{s}\" for s in subs]:",
            "    entry = projects.setdefault(path, {})",
            '    entry["hasTrustDialogAccepted"] = True',
            'with open(cfg, "w") as f: json.dump(data, f, indent=2)',
            "PY",
            "fi",
            "",
        ]

    first = True
    for a in agents:
        local = a["local"]
        if a["runtime"] == "claude":
            # --dangerously-skip-permissions is required for autonomous agents:
            # without it, every tool call (Bash, Edit, …) hits a permission prompt
            # that the model can't dismiss. The bypass-permissions warning that
            # follows is dismissed below by dismiss_bypass.
            inner = 'set -a; . ./.env; set +a; exec claude --dangerously-skip-permissions "上班"'
        else:
            inner = 'set -a; . ./.env; set +a; exec codex "查收件箱并按 AGENT.md 处理"'
        cwd_path = f"agents/{local}"
        if first:
            lines.append(
                f'tmux new-session -d -s "$SESSION" -n {shlex.quote(local)} '
                f'-c {shlex.quote(cwd_path)} {shlex.quote(inner)}'
            )
            first = False
        else:
            lines.append(
                f'tmux new-window -t "$SESSION" -n {shlex.quote(local)} '
                f'-c {shlex.quote(cwd_path)} {shlex.quote(inner)}'
            )

    if has_claude:
        # Dismiss the "Bypass permissions mode?" warning that
        # --dangerously-skip-permissions triggers on every claude boot. Acceptance
        # is session-only (not persisted), so this fires every restart. Press "2"
        # only on panes whose buffer actually shows the dialog, and only once each,
        # otherwise the digit becomes a stray char in claude's input.
        claude_locals = [a["local"] for a in agents if a["runtime"] == "claude"]
        lines += [
            "",
            "# Dismiss bypass-permissions warning on each claude pane (max 12 polls).",
            f"CLAUDE_PANES=({' '.join(shlex.quote(l) for l in claude_locals)})",
            'declare -A BYPASS_SENT=()',
            'for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do',
            '  sleep 1',
            '  remaining=0',
            '  for w in "${CLAUDE_PANES[@]}"; do',
            '    [ "${BYPASS_SENT[$w]:-}" = "1" ] && continue',
            '    if tmux capture-pane -p -t "$SESSION:$w" 2>/dev/null | grep -q "Yes, I accept"; then',
            '      tmux send-keys -t "$SESSION:$w" "2"',
            '      BYPASS_SENT[$w]=1',
            '    else',
            '      remaining=1',
            '    fi',
            '  done',
            '  [ $remaining -eq 0 ] && break',
            'done',
        ]

    if has_codex:
        lines += [
            "",
            "# Codex panes don't self-tick — start the external watcher daemon.",
            'mkdir -p .agent-mailer',
            'PIDFILE=".agent-mailer/codex-tick.pid"',
            'LOGFILE=".agent-mailer/codex-tick.log"',
            'CONFIG=".agent-mailer/codex-ticks.json"',
            f'DAEMON={shlex.quote(daemon_bin)}',
            'if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then',
            '  echo "codex-tick already running (PID $(cat "$PIDFILE"))"',
            'else',
            '  nohup "$DAEMON" --config "$CONFIG" >> "$LOGFILE" 2>&1 &',
            '  echo $! > "$PIDFILE"',
            '  echo "codex-tick started (PID $(cat "$PIDFILE"))"',
            'fi',
        ]

    lines += [
        "",
        'exec tmux attach -t "$SESSION"',
    ]
    return "\n".join(lines) + "\n"


def _render_stop_team_sh(team_name: str, has_codex: bool) -> str:
    session = f"agent-mailer-{team_name}"
    parts = [
        "#!/usr/bin/env bash",
        "# Generated by `agent-mailer up-team`. Re-run up-team to regenerate.",
        "set -euo pipefail",
        "",
        'cd "$(dirname "$0")"',
        f"SESSION={shlex.quote(session)}",
        "",
    ]
    if has_codex:
        parts += [
            'PIDFILE=".agent-mailer/codex-tick.pid"',
            'if [ -f "$PIDFILE" ]; then',
            '  PID=$(cat "$PIDFILE")',
            '  if kill -0 "$PID" 2>/dev/null; then',
            '    kill "$PID" || true',
            '    echo "codex-tick stopped (PID $PID)"',
            '  fi',
            '  rm -f "$PIDFILE"',
            'fi',
            "",
        ]
    parts += [
        'if tmux has-session -t "$SESSION" 2>/dev/null; then',
        '  tmux kill-session -t "$SESSION"',
        '  echo "Session $SESSION stopped."',
        'else',
        '  echo "Session $SESSION not running."',
        'fi',
    ]
    return "\n".join(parts) + "\n"


_GITIGNORE_BLOCK_MARKER = "# agent-mailer team artifacts"
_GITIGNORE_ENTRIES = ["agents/", "start-team.sh", "stop-team.sh", ".agent-mailer/"]


def _update_gitignore(out_dir: Path) -> None:
    gi = out_dir / ".gitignore"
    existing_text = gi.read_text() if gi.exists() else ""
    existing_lines = existing_text.splitlines()
    existing_set = set(existing_lines)

    additions: list[str] = []
    if _GITIGNORE_BLOCK_MARKER not in existing_set:
        additions.append(_GITIGNORE_BLOCK_MARKER)
    for e in _GITIGNORE_ENTRIES:
        if e not in existing_set:
            additions.append(e)

    if not additions:
        return

    out = existing_text
    if out and not out.endswith("\n"):
        out += "\n"
    if existing_lines:
        out += "\n"  # blank line separator
    out += "\n".join(additions) + "\n"
    gi.write_text(out)


async def _up_team(args, *, client: httpx.AsyncClient | None = None):
    yaml_path = Path(args.yaml_path)
    if not yaml_path.exists():
        print(f"Error: {yaml_path} not found.", file=sys.stderr)
        sys.exit(1)
    try:
        raw = yaml.safe_load(yaml_path.read_text())
    except yaml.YAMLError as e:
        print(f"Error: failed to parse {yaml_path}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        spec = _validate_team_spec(raw)
    except ValueError as e:
        print(f"Error: invalid team.yaml: {e}", file=sys.stderr)
        sys.exit(1)

    # broker_url precedence: CLI flag > yaml > credentials default > hardcoded.
    if not getattr(args, "broker_url", None) and spec.get("broker_url"):
        args.broker_url = spec["broker_url"]
    broker_url, session = load_session(args)

    payload = {
        "name": spec["team"],
        "description": spec["description"],
        "agents": [
            {
                "name": a["name"],
                "address_local": a["address_local"],
                "role": a["role"],
                "description": a["description"],
                "system_prompt": a["system_prompt"],
                "tags": a["tags"],
            }
            for a in spec["agents"]
        ],
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            f"{broker_url}/admin/teams/bootstrap",
            json=payload,
            headers={"Authorization": f"Bearer {session['token']}"},
        )
    finally:
        if own_client:
            await client.aclose()

    if resp.status_code == 401:
        print(
            f"Error: session expired. Run "
            f"`agent-mailer login --broker-url {broker_url}` again.",
            file=sys.stderr,
        )
        sys.exit(1)
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"Error: bootstrap failed ({resp.status_code}): {detail}", file=sys.stderr)
        sys.exit(1)

    body = resp.json()

    out_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    runtime_by_name = {a["name"]: a["runtime"] for a in spec["agents"]}
    enriched = []
    for ar in body["agents"]:
        local = ar["address"].split("@")[0]
        enriched.append({
            **ar,
            "runtime": runtime_by_name.get(ar["name"], "claude"),
            "local": local,
        })

    agents_root = out_dir / "agents"
    agents_root.mkdir(parents=True, exist_ok=True)
    for a in enriched:
        ad = agents_root / a["local"]
        ad.mkdir(parents=True, exist_ok=True)
        (ad / "AGENT.md").write_text(a["agent_md"])
        env_path = ad / ".env"
        env_path.write_text(
            f"AMP_API_KEY={a['api_key_plaintext']}\n"
            f"AMP_BROKER_URL={broker_url}\n"
            f"AMP_AGENT_ADDRESS={a['address']}\n"
            f"AMP_AGENT_ID={a['agent_id']}\n"
        )
        os.chmod(env_path, 0o600)

    has_codex = any(a["runtime"] == "codex" for a in enriched)
    if has_codex:
        amp_dir = out_dir / ".agent-mailer"
        amp_dir.mkdir(parents=True, exist_ok=True)
        ticks_config = {
            "agents": [
                {
                    "name": a["name"],
                    "agent_dir": str((agents_root / a["local"]).resolve()),
                    "pane": f"agent-mailer-{spec['team']}:{a['local']}",
                }
                for a in enriched
                if a["runtime"] == "codex"
            ],
        }
        (amp_dir / "codex-ticks.json").write_text(json.dumps(ticks_config, indent=2))

    start_path = out_dir / "start-team.sh"
    stop_path = out_dir / "stop-team.sh"
    start_path.write_text(_render_start_team_sh(spec["team"], enriched))
    stop_path.write_text(_render_stop_team_sh(spec["team"], has_codex))
    os.chmod(start_path, 0o755)
    os.chmod(stop_path, 0o755)

    _update_gitignore(out_dir)

    print(f"Team '{spec['team']}' bootstrapped on {broker_url}.")
    print(f"  Team ID: {body['team']['id']}")
    for a in enriched:
        print(f"  - {a['name']} ({a['runtime']}) — {a['address']}")
    print()
    print("Next: ./start-team.sh")


def main():
    parser = argparse.ArgumentParser(prog="agent-mailer", description="Agent Mailer CLI")
    parser.add_argument("--db", default=DB_PATH, help="Database file path")
    subparsers = parser.add_subparsers(dest="command")

    # bootstrap-admin
    bp = subparsers.add_parser("bootstrap-admin", help="Create first superadmin user")
    bp.add_argument("--username", required=True, help="Admin username")
    bp.add_argument("--password", required=True, help="Admin password")

    # generate-invite-code
    gi = subparsers.add_parser("generate-invite-code", help="Generate an invite code")
    gi.add_argument("--username", required=True, help="Superadmin username")
    gi.add_argument("--password", required=True, help="Superadmin password")

    # migrate-db
    md = subparsers.add_parser("migrate-db", help="Migrate local-mode DB to SaaS mode")
    md.add_argument("--password", required=True, help="Password for the admin user")

    # login
    lg = subparsers.add_parser("login", help="Authenticate against a broker and cache the session token")
    lg.add_argument("--broker-url", help=f"Broker URL (default: {DEFAULT_BROKER_URL})")
    lg.add_argument("--username", help="Username (prompts if omitted)")
    lg.add_argument("--password", help="Password (prompts if omitted)")
    lg.add_argument("--credentials-path", help=argparse.SUPPRESS)

    # logout
    lo = subparsers.add_parser("logout", help="Clear cached session token(s)")
    lo.add_argument("--broker-url", help="Broker URL to clear (default: clear all)")
    lo.add_argument("--credentials-path", help=argparse.SUPPRESS)

    # up-team
    ut = subparsers.add_parser(
        "up-team",
        help="Bootstrap a team from team.yaml: register agents and write launcher scripts",
    )
    ut.add_argument("yaml_path", help="Path to team.yaml")
    ut.add_argument("--broker-url", help="Override broker URL (defaults to yaml/credentials)")
    ut.add_argument("--output-dir", help=argparse.SUPPRESS)
    ut.add_argument("--credentials-path", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "bootstrap-admin":
        asyncio.run(_bootstrap_admin(args))
    elif args.command == "generate-invite-code":
        asyncio.run(_generate_invite_code(args))
    elif args.command == "migrate-db":
        asyncio.run(_migrate_db(args))
    elif args.command == "login":
        asyncio.run(_login(args))
    elif args.command == "logout":
        asyncio.run(_logout(args))
    elif args.command == "up-team":
        asyncio.run(_up_team(args))


if __name__ == "__main__":
    main()
