"""Prompt builders for the spawned Claude subprocess (§10.2).

M2 only ships the "fresh thread" template. The "resume" branch is
prepared but currently unused — `is_resume` is wired through so M3 can
flip it on without touching this module's public surface.
"""
from __future__ import annotations

from agent_mailer_cli.broker import InboxMessage

FRESH_TEMPLATE = """\
You have a new task in a fresh thread.

Message: {msg_id}
Thread:  {thread_id}
From:    {from_address}
Subject: {subject}

Steps:
1. Read AGENT.md in the current directory for your identity.
2. Read your global memory: .agent-mailer/memory/global.md (if it exists).
3. GET {broker_url}/messages/{msg_id} (header X-API-Key from .agent-mailer/config.toml) to fetch the full message body.
4. GET {broker_url}/messages/thread/{thread_id} for any prior context.
5. Execute according to your system_prompt in AGENT.md.
6. POST {broker_url}/messages/send to reply or forward as appropriate.
7. Before exiting, Edit .agent-mailer/memory/{thread_id}.md with:
   - Your key non-obvious judgments
   - What you tried and ruled out
   - Open questions or planned next steps
8. PATCH {broker_url}/messages/{msg_id}/read to mark as handled.
"""

RESUME_TEMPLATE = """\
A new message arrived in our active thread.

Message: {msg_id}
Thread:  {thread_id}

You already have full context from prior turns in this conversation.

Steps:
1. Read your handoff notes: .agent-mailer/memory/{thread_id}.md
2. GET {broker_url}/messages/{msg_id}
3. Continue work per our prior reasoning.
4. POST {broker_url}/messages/send to reply or forward.
5. Update .agent-mailer/memory/{thread_id}.md if you reached new insights.
6. PATCH {broker_url}/messages/{msg_id}/read.
"""


def build_prompt(msg: InboxMessage, *, broker_url: str, is_resume: bool = False) -> str:
    template = RESUME_TEMPLATE if is_resume else FRESH_TEMPLATE
    return template.format(
        msg_id=msg.id,
        thread_id=msg.thread_id,
        from_address=msg.from_agent,
        subject=msg.subject,
        broker_url=broker_url.rstrip("/"),
    )
