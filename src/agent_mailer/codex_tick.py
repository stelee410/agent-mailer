"""External tick daemon for Codex agents.

Codex CLI lacks Claude Code's ``CronCreate`` primitive, so a
self-scheduling ``shangban`` skill cannot work there. This daemon fills
the gap: every ``--interval`` seconds it polls the broker inbox for each
registered codex agent, and when there is unread mail and the pane is
idle (content stable across a short capture window) it injects a
``查收`` keystroke via ``tmux send-keys``.

Configuration lives at ``.agent-mailer/codex-ticks.json`` (written by
``agent-mailer up-team``). Each entry points at one agent's working
directory; the daemon re-reads ``<agent_dir>/.env`` each tick so the
secret stays in a single 0600 file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a simple ``KEY=value`` ``.env`` file."""
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        # Strip optional surrounding quotes — we never write them ourselves
        # but be tolerant if a human edits the file.
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def capture_pane(target: str) -> str:
    r = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", target],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout if r.returncode == 0 else ""


def pane_is_idle(target: str, settle_sec: float = 1.0) -> bool:
    """Pane is idle if its rendered content does not change across ``settle_sec``.

    Works for any TUI: a busy app keeps redrawing (streaming output,
    progress spinners), so two captures separated by ~1 s differ. An
    idle app — sitting at a prompt — produces identical captures.
    """
    a = capture_pane(target)
    if not a:
        return False
    time.sleep(settle_sec)
    b = capture_pane(target)
    return a == b


def send_keys(target: str, text: str) -> None:
    subprocess.run(
        ["tmux", "send-keys", "-t", target, text, "Enter"],
        check=False,
        timeout=5,
    )


async def has_unread(broker_url: str, address: str, agent_id: str, api_key: str,
                    *, client: httpx.AsyncClient | None = None) -> bool:
    """Return True if the agent's inbox has unread (actionable) messages."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=10.0)
    try:
        r = await client.get(
            f"{broker_url.rstrip('/')}/messages/inbox/{address}",
            params={"agent_id": agent_id},
            headers={"X-API-Key": api_key},
        )
    finally:
        if own:
            await client.aclose()
    if r.status_code != 200:
        return False
    body = r.json()
    if isinstance(body, list):
        return len(body) > 0
    if isinstance(body, dict) and "messages" in body:
        return len(body["messages"]) > 0
    return False


def load_config(path: Path) -> list[dict]:
    """Return the list of registered codex agents, or [] if missing."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    agents = data.get("agents") if isinstance(data, dict) else None
    return agents if isinstance(agents, list) else []


async def tick_one(entry: dict, *, client: httpx.AsyncClient | None = None,
                   tmux_send=send_keys, tmux_idle=pane_is_idle) -> str:
    """Process one agent. Returns a short outcome string for logs/tests."""
    agent_dir = Path(entry["agent_dir"])
    pane = entry["pane"]
    env = parse_env_file(agent_dir / ".env")

    address = env.get("AMP_AGENT_ADDRESS")
    agent_id = env.get("AMP_AGENT_ID")
    api_key = env.get("AMP_API_KEY")
    broker_url = env.get("AMP_BROKER_URL")
    if not all([address, agent_id, api_key, broker_url]):
        return "skip:bad-env"

    if not await has_unread(broker_url, address, agent_id, api_key, client=client):
        return "skip:empty-inbox"

    if not tmux_idle(pane):
        return "skip:pane-busy"

    tmux_send(pane, "查收")
    return "sent"


async def main_loop(config_path: Path, interval: float, *, log=print) -> None:
    """Run forever (until SIGTERM). Each iteration: read config, tick each agent."""
    while True:
        agents = load_config(config_path)
        if not agents:
            # Config gone or empty — daemon has nothing to do.
            log(f"[codex-tick] no agents in {config_path}, exiting.")
            return
        for entry in agents:
            try:
                outcome = await tick_one(entry)
                if outcome == "sent":
                    log(f"[codex-tick] {entry.get('name', entry.get('pane'))}: {outcome}")
            except Exception as exc:  # pragma: no cover - defensive
                log(f"[codex-tick] error for {entry.get('pane')}: {exc!r}")
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-mailer-codex-tick")
    parser.add_argument(
        "--config",
        default=".agent-mailer/codex-ticks.json",
        help="Path to codex-ticks.json (default: .agent-mailer/codex-ticks.json)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between ticks (default: 60)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main_loop(Path(args.config), args.interval))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
