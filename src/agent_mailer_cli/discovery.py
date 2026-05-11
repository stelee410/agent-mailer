"""Resolve agent identity from the §7.2 priority chain.

Order: CLI args > env vars > config.toml > AGENT.md > error.

We never *write* during discovery; the wizard is responsible for filling
in missing values. Discovery is allowed to return a partially populated
Config — callers decide whether to dispatch the wizard or refuse.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent_mailer_cli.agent_md import AgentMdInfo, find_agent_md, parse_agent_md
from agent_mailer_cli.config import Config, load_config

ENV_MAP = {
    "AGENT_MAILER_API_KEY": "api_key",
    "AGENT_MAILER_BROKER_URL": "broker_url",
    "AGENT_MAILER_AGENT_ID": "agent_id",
    "AGENT_MAILER_ADDRESS": "address",
    "AGENT_MAILER_AGENT_NAME": "agent_name",
    "AGENT_MAILER_PERMISSION_MODE": "permission_mode",
}


@dataclass
class DiscoveryResult:
    config: Config
    config_existed: bool
    agent_md: AgentMdInfo
    agent_md_path: Optional[Path]
    sources: dict[str, str]  # field name → "cli" | "env" | "config" | "agent_md"


def discover(workdir: Path, **cli_overrides: object) -> DiscoveryResult:
    cfg = load_config(workdir)
    config_existed = cfg is not None
    if cfg is None:
        cfg = Config(workdir=workdir)
    else:
        cfg.workdir = workdir

    sources: dict[str, str] = {}
    if config_existed:
        for name in ("agent_id", "agent_name", "address", "broker_url", "api_key", "permission_mode"):
            if getattr(cfg, name):
                sources[name] = "config"

    agent_md_path = find_agent_md(workdir)
    md_info = parse_agent_md(agent_md_path) if agent_md_path else AgentMdInfo()
    if md_info.agent_id and not cfg.agent_id:
        cfg.agent_id = md_info.agent_id
        sources["agent_id"] = "agent_md"
    if md_info.agent_name and not cfg.agent_name:
        cfg.agent_name = md_info.agent_name
        sources["agent_name"] = "agent_md"
    if md_info.address and not cfg.address:
        cfg.address = md_info.address
        sources["address"] = "agent_md"
    if md_info.broker_url and not cfg.broker_url:
        cfg.broker_url = md_info.broker_url
        sources["broker_url"] = "agent_md"

    for env_name, attr in ENV_MAP.items():
        value = os.environ.get(env_name)
        if value:
            setattr(cfg, attr, value)
            sources[attr] = "env"

    for attr, value in cli_overrides.items():
        if value is None or value == "":
            continue
        if not hasattr(cfg, attr):
            continue
        setattr(cfg, attr, value)
        sources[attr] = "cli"

    return DiscoveryResult(
        config=cfg,
        config_existed=config_existed,
        agent_md=md_info,
        agent_md_path=agent_md_path,
        sources=sources,
    )
