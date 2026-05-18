"""Helpers for `agent-mailer team init` — empty-dir check, broker calls, role layout.

This is the Python port of the v0.1.x amp-team Node package, with two structural
upgrades:

1. Each role directory becomes a full `agent-mailer watch` workdir
   (config.toml + AGENT.md/SOUL.md), so the generated `start-<role>.sh`
   launches the watch loop rather than the agent CLI directly. Result:
   "agent only spawns when a new mail arrives" — what human asked for.

2. v0.1.1 P1-3 invariant carries over: persist credentials *before* fetching
   the per-agent setup so a transient /setup 5xx never strands the
   api_key_plaintext (broker-side one-shot).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agent_mailer_cli.config import Config, save_config


DEFAULT_BROKER_URL = "https://amp.linkyun.co"

# Entries that don't disqualify a directory from being treated as "empty".
# Carried over from amp-team v0.1.1; plus the v0.1.2 nice-to-haves PM
# greenlit (.idea/.vscode/.editorconfig/.envrc — common at the project root
# before the team has any code committed).
ALLOWED_NOISE = frozenset({
    ".git",
    ".DS_Store",
    ".gitignore",
    ".idea",
    ".vscode",
    ".editorconfig",
    ".envrc",
    "Thumbs.db",
})

ROLES = ("pm", "dev", "reviewer", "support")

SUPPORTED_FRAMEWORKS = ("claude", "codex", "infiniti")
COMING_SOON_FRAMEWORKS = ("openclaw", "dreamfactory")

# Broker address regex (mirrors the server's _ADDRESS_LOCAL_RE).
_ADDRESS_LOCAL_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,61}[a-z0-9])?$")


class TeamSetupError(Exception):
    """Raised on a validation or broker error during team init."""


@dataclass
class CreatedAgent:
    role: str
    framework: str
    agent_id: str
    address: str
    api_key_plaintext: str
    agent_md: str = ""
    runtime_md: str = ""  # CLAUDE.md / INFINITI.md / etc.
    runtime_md_filename: str = ""
    identity_filename: str = "AGENT.md"


# ---------- empty-dir guard ----------


def check_empty_dir(workdir: Path) -> None:
    """Raise TeamSetupError if workdir contains anything outside ALLOWED_NOISE."""
    try:
        entries = sorted(p.name for p in workdir.iterdir())
    except FileNotFoundError as exc:
        raise TeamSetupError(f"directory does not exist: {workdir}") from exc
    blockers = [name for name in entries if name not in ALLOWED_NOISE]
    if not blockers:
        return
    head = ", ".join(blockers[:5])
    if len(blockers) > 5:
        head += f", ... (+{len(blockers) - 5} more)"
    raise TeamSetupError(
        f"directory is not empty — found {len(blockers)} unexpected "
        f"entr{'y' if len(blockers) == 1 else 'ies'}: {head}"
    )


# ---------- team slug ----------


def slugify_team(raw: str) -> str:
    lower = (raw or "").strip().lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", lower)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-._")
    # Reserve enough room for "-reviewer" (longest role suffix, 9 chars).
    max_len = 63 - len("-reviewer")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("._-")
    return slug


def is_valid_team_slug(slug: str) -> bool:
    return bool(slug) and bool(re.fullmatch(r"[a-z0-9]([a-z0-9._-]{0,53}[a-z0-9])?", slug))


# ---------- broker calls ----------


def login(client: httpx.Client, broker_url: str, username: str, password: str) -> str:
    """POST /users/login → return JWT (Bearer) token. Raises TeamSetupError on failure."""
    resp = client.post(
        f"{broker_url}/users/login",
        json={"username": username, "password": password},
    )
    if resp.status_code == 401:
        raise TeamSetupError("invalid username or password")
    if resp.status_code != 200:
        raise TeamSetupError(
            f"login failed (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    data = resp.json()
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise TeamSetupError("login response missing 'token'")
    return token


def create_agent(
    client: httpx.Client,
    broker_url: str,
    token: str,
    *,
    name: str,
    role: str,
    description: str,
    system_prompt: str,
) -> dict[str, Any]:
    """POST /users/me/agents → return UserAgentCreateResponse dict including api_key_plaintext."""
    resp = client.post(
        f"{broker_url}/users/me/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "address_local": name,
            "role": role,
            "description": description,
            "system_prompt": system_prompt,
        },
    )
    if resp.status_code not in (200, 201):
        raise TeamSetupError(
            f"create agent {name!r} failed (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    data = resp.json()
    for required in ("id", "address", "api_key_plaintext"):
        if not isinstance(data.get(required), str) or not data[required]:
            raise TeamSetupError(
                f"create-agent response missing {required!r} for {name!r}"
            )
    return data


def fetch_agent_setup(
    client: httpx.Client,
    broker_url: str,
    agent_id: str,
    api_key: str,
) -> dict[str, str]:
    """GET /agents/{id}/setup → {agent_md, claude_md, infiniti_md, instructions}.

    Authenticates with the agent's own X-API-Key (broker requires
    get_api_key_user on this endpoint, not the user JWT).
    """
    resp = client.get(
        f"{broker_url}/agents/{agent_id}/setup",
        headers={"X-API-Key": api_key},
    )
    if resp.status_code != 200:
        raise TeamSetupError(
            f"fetch setup for agent {agent_id} failed "
            f"(HTTP {resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


# ---------- role-dir materialization ----------


def write_partial_credentials(
    workdir: Path,
    role: str,
    framework: str,
    agent: dict[str, Any],
    broker_url: str,
    *,
    project_dir: str = "",
    permission_mode: str = "acceptEdits",
) -> Path:
    """Write a complete config.toml for this role with `partial_setup_pending` marker.

    Called immediately after createAgent succeeds, BEFORE fetching the per-agent
    /setup. The marker lets `agent-mailer team init` recover (or the user
    manually re-run setup) without losing the one-shot api_key_plaintext.
    """
    role_dir = workdir / role
    cfg_dir = role_dir / ".agent-mailer"
    cfg_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(cfg_dir, 0o700)

    cfg = Config(
        workdir=role_dir,
        agent_id=agent["id"],
        agent_name=agent.get("name", f"team-{role}"),
        address=agent["address"],
        api_key=agent["api_key_plaintext"],
        broker_url=broker_url,
        permission_mode=permission_mode,
        runtime=framework,
        project_dir=project_dir,
    )
    save_config(cfg)

    marker_path = cfg_dir / "partial_setup_pending"
    marker_path.write_text(
        json.dumps(
            {
                "role": role,
                "framework": framework,
                "agent_id": agent["id"],
                "address": agent["address"],
                "reason": "setup fetch pending or failed",
                "marked_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(marker_path, 0o600)
    return cfg.cfg_file


def write_identity_files(
    workdir: Path,
    role: str,
    framework: str,
    setup_resp: dict[str, str],
) -> None:
    """Drop AGENT.md / SOUL.md + the runtime adapter file in the role dir.

    Infiniti uses SOUL.md (per broker /setup `instructions`); claude/codex use
    AGENT.md and have a CLAUDE.md adapter (codex follows the same convention).
    """
    role_dir = workdir / role
    if framework == "infiniti":
        (role_dir / "SOUL.md").write_text(setup_resp.get("agent_md", ""), encoding="utf-8")
        (role_dir / "INFINITI.md").write_text(
            setup_resp.get("infiniti_md", ""), encoding="utf-8"
        )
    else:
        (role_dir / "AGENT.md").write_text(setup_resp.get("agent_md", ""), encoding="utf-8")
        (role_dir / "CLAUDE.md").write_text(setup_resp.get("claude_md", ""), encoding="utf-8")


def finalize_role(workdir: Path, role: str) -> None:
    """Remove the partial_setup_pending marker once setup files are on disk."""
    marker = workdir / role / ".agent-mailer" / "partial_setup_pending"
    if marker.exists():
        marker.unlink()


# Allow Claude Code's non-interactive `-p` mode to actually hit the broker.
# Claude's `acceptEdits` permission mode auto-approves only file edits — it
# stops on Bash/network with "This command requires approval", which the
# headless watcher can't answer. Surgical allowlist lets curl + agent-mailer
# through without the blast radius of `bypassPermissions`.
_CLAUDE_BROKER_ALLOWLIST = [
    "Bash(curl:*amp.linkyun.co*)",
    "Bash(agent-mailer:*)",
    "WebFetch(domain:amp.linkyun.co)",
]


def write_runtime_settings(workdir: Path, role: str, framework: str) -> None:
    """Drop runtime-specific config so the spawned agent can call the broker.

    - claude → `<role>/.claude/settings.json` permissions.allow allowlist.
      Without this, claude's `acceptEdits` mode kills every curl with
      "This command requires approval" and headless `-p` mode can't answer.
    - codex / infiniti → no-op (codex_runner already passes
      `--ask-for-approval never`; infiniti CLI surfaces no approval flag).
    """
    if framework != "claude":
        return
    claude_dir = workdir / role / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    settings = {"permissions": {"allow": list(_CLAUDE_BROKER_ALLOWLIST)}}
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.chmod(settings_path, 0o644)


def write_start_script(workdir: Path, role: str) -> Path:
    """Write start-<role>.sh that cd's into the role workdir and execs `agent-mailer watch`.

    Generated mode is 0755. On Windows users would `cd <role> && agent-mailer watch`
    manually; we ship a .cmd wrapper for parity.
    """
    sh_path = workdir / f"start-{role}.sh"
    sh_body = (
        "#!/bin/sh\n"
        "# Generated by `agent-mailer team init`. Re-run to refresh.\n"
        "set -e\n"
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        f'cd "$DIR/{role}"\n'
        "exec agent-mailer watch\n"
    )
    sh_path.write_text(sh_body, encoding="utf-8")
    os.chmod(sh_path, 0o755)

    cmd_path = workdir / f"start-{role}.cmd"
    cmd_body = (
        "@echo off\r\n"
        "REM Generated by `agent-mailer team init`. Re-run to refresh.\r\n"
        f'cd /d "%~dp0{role}"\r\n'
        "agent-mailer watch\r\n"
    )
    cmd_path.write_text(cmd_body, encoding="utf-8")
    return sh_path


def write_team_meta(workdir: Path, meta: dict[str, Any]) -> Path:
    meta_dir = workdir / ".amp-team"
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = meta_dir / "team.json"
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


# ---------- system prompt scaffolding ----------


SYSTEM_PROMPTS: dict[str, str] = {
    "pm": (
        "你是 {team} 团队的产品经理 (PM)。核心职责：1) 接收 human 需求，澄清边界条件、"
        "范围、优先级；2) 把需求拆为可执行任务，派给 Dev / Reviewer / Support；"
        "3) 在 thread 中保持决策可追溯（每个拍板附 message_id 引用）；"
        "4) 暴露 trade-off 给 human 拍板，不替属于上层的决策做主。"
    ),
    "dev": (
        "你是 {team} 团队的开发工程师 (Dev)。核心职责：1) 根据 PM 派单实现代码；"
        "2) 遵循既有技术栈与编码规范，改动聚焦；3) 主动暴露技术债、边界情况、依赖阻塞；"
        "4) 交付时给出关键文件路径、变更摘要、commit hash、自审 grep。"
    ),
    "reviewer": (
        "你是 {team} 团队的代码审核者 (Reviewer)。核心职责：1) 审 Dev 交付的实现是否满足 SPEC "
        "和 PRD；2) 找 lock-in test、勿绕过的不变量、prompt injection 等高危反模式；"
        "3) 主动撤回误判（先怀疑再验证再认错）；4) 给出 P0-P3 分级的具体修复建议。"
    ),
    "support": (
        "你是 {team} 团队的客户支持 (Support)。核心职责：1) 接收 user / customer 工单；"
        "2) 复述问题以确认理解，必要时升级给 Dev / PM；3) 答复时给可操作的下一步，"
        "不只是「我们正在跟进」；4) 把 recurring issue 抽象为 FAQ 或 bug 报告。"
    ),
}


def system_prompt_for(role: str, team: str) -> str:
    template = SYSTEM_PROMPTS.get(role, "你是 {team} 团队的成员，角色 " + role + "。")
    return template.format(team=team)
