"""SPEC §15.6 invariant #5: AGENT.md ↔ config.toml agent_id consistency.

Centralized so both `watch_cmd` and `doctor_cmd` enforce the same rule with
the same error text.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent_mailer_cli.agent_md import AgentMdInfo, find_agent_md, parse_agent_md
from agent_mailer_cli.config import Config


@dataclass
class ConsistencyResult:
    ok: bool
    agent_md_path: Optional[Path]
    config_agent_id: str
    agent_md_agent_id: Optional[str]
    detail: str


def check_agent_id_consistency(workdir: Path, cfg: Config) -> ConsistencyResult:
    """Compare AGENT.md's agent_id to config.toml's agent_id.

    If AGENT.md is absent or doesn't carry an agent_id, the check is OK
    (nothing to compare). If both are present and they differ, fail.
    """
    md_path = find_agent_md(workdir)
    if md_path is None:
        return ConsistencyResult(
            ok=True, agent_md_path=None,
            config_agent_id=cfg.agent_id,
            agent_md_agent_id=None,
            detail="AGENT.md not present; consistency check skipped.",
        )
    md = parse_agent_md(md_path)
    if not md.agent_id:
        return ConsistencyResult(
            ok=True, agent_md_path=md_path,
            config_agent_id=cfg.agent_id,
            agent_md_agent_id=None,
            detail="AGENT.md has no agent_id field; nothing to compare.",
        )
    if md.agent_id == cfg.agent_id:
        return ConsistencyResult(
            ok=True, agent_md_path=md_path,
            config_agent_id=cfg.agent_id,
            agent_md_agent_id=md.agent_id,
            detail=f"agent_id matches between AGENT.md and config.toml ({cfg.agent_id}).",
        )
    return ConsistencyResult(
        ok=False, agent_md_path=md_path,
        config_agent_id=cfg.agent_id,
        agent_md_agent_id=md.agent_id,
        detail=(
            f"agent_id mismatch:\n"
            f"  config.toml: {cfg.agent_id!r}\n"
            f"  AGENT.md:    {md.agent_id!r}  ({md_path})\n"
            f"This usually means AGENT.md was hand-edited to reference a different "
            f"agent than the one this workdir is registered for.\n"
            f"Fix: align AGENT.md with config.toml, OR pass "
            f"--ignore-agent-md-mismatch if this is intentional (e.g. fixture)."
        ),
    )
