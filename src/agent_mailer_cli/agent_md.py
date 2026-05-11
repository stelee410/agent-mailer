"""AGENT.md parser used at wizard time only.

Runtime never depends on AGENT.md — config.toml is authoritative. This
parser is intentionally permissive: it accepts the bullet-list and
heading-paragraph styles produced by the broker setup endpoint, and
returns whatever fields it can extract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Pattern: "- **Name**: value" or "- **Address**: value"
_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*([^*]+)\*\*\s*:\s*(.+?)\s*$")
# Fallback for plain "Name: value" lines (no bold).
_PLAIN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z _\-]*?)\s*:\s*(.+?)\s*$")

_LABEL_MAP = {
    "name": "agent_name",
    "agent name": "agent_name",
    "agent_name": "agent_name",
    "role": "agent_role",
    "address": "address",
    "agent address": "address",
    "agent id": "agent_id",
    "agent_id": "agent_id",
    "id": "agent_id",
    "broker": "broker_url",
    "broker url": "broker_url",
    "broker_url": "broker_url",
}


@dataclass
class AgentMdInfo:
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    address: Optional[str] = None
    broker_url: Optional[str] = None
    agent_role: Optional[str] = None

    def is_empty(self) -> bool:
        return not any([self.agent_id, self.agent_name, self.address, self.broker_url])


def parse_agent_md(path: Path) -> AgentMdInfo:
    """Parse a workdir AGENT.md. Returns an AgentMdInfo with whatever was found.

    Stops scanning the body once it crosses into a "code block" or a "Mail Broker"
    style protocol section — those frequently mention an `agent_id` or address as
    documentation and would clobber the real identity if we kept matching.
    """
    info = AgentMdInfo()
    if not path.exists():
        return info

    text = path.read_text(encoding="utf-8")
    in_fence = False
    in_protocol_section = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Scoping heuristic: section headings that introduce protocol examples.
        if line.startswith("#"):
            heading = line.lstrip("# ").lower()
            in_protocol_section = (
                "protocol" in heading
                or "邮箱协议" in heading
                or "api" in heading
                or "system prompt" in heading
                or "身份提示词" in heading
            )
            continue
        if in_protocol_section:
            continue

        match = _BULLET_RE.match(line) or _PLAIN_RE.match(line)
        if not match:
            continue
        label, value = match.group(1).strip().lower(), match.group(2).strip()
        # Strip surrounding backticks (common in markdown).
        if value.startswith("`") and value.endswith("`") and len(value) >= 2:
            value = value[1:-1]
        field = _LABEL_MAP.get(label)
        if field is None:
            continue
        # Don't overwrite a value already set; the first occurrence wins.
        if getattr(info, field) is None:
            setattr(info, field, value)
    return info


def find_agent_md(workdir: Path) -> Optional[Path]:
    candidate = workdir / "AGENT.md"
    return candidate if candidate.exists() else None
