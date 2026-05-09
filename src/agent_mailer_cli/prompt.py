"""Prompt builders for the spawned Claude subprocess (§10.2).

SPEC §22 mandates that the watcher pass ONLY message metadata that the
broker can authenticate (msg_id, thread_id, from_agent — bound to an
api_key) into the prompt; user-controllable fields (subject, body,
attachments) must be fetched by claude itself via GET so they cross a
clear data boundary instead of bleeding into the instruction stream.

M3 enables session resume. `build_prompt` now accepts a
`stale_session_note` to support the §11.3 fallback when a thread's
session is too old to resume.
"""
from __future__ import annotations

from typing import Optional

from agent_mailer_cli.broker import InboxMessage

FRESH_TEMPLATE = """\
You have a new task in a fresh thread.

Message: {msg_id}
Thread:  {thread_id}
From:    {from_address}

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


def build_prompt(
    msg: InboxMessage,
    *,
    broker_url: str,
    is_resume: bool = False,
    stale_session_note: Optional[str] = None,
) -> str:
    # SPEC §22: msg.subject and msg.raw must never reach this format dict —
    # they are user-controlled fields that would create a prompt-injection
    # vector. claude fetches them itself via GET /messages/{msg_id}.
    template = RESUME_TEMPLATE if is_resume else FRESH_TEMPLATE
    body = template.format(
        msg_id=msg.id,
        thread_id=msg.thread_id,
        from_address=msg.from_agent,
        broker_url=broker_url.rstrip("/"),
    )
    if stale_session_note:
        body = body + "\nNOTE: " + stale_session_note + "\n"
    return body


def build_stale_session_note(*, age_days: int, turn_count: int, memory_dir: str,
                             thread_id: str) -> str:
    """SPEC §11.3 fallback note inserted when a session is too old to resume.

    `memory_dir` is the relative path inside the workdir (typically
    `.agent-mailer/memory`). thread_id selects the per-thread handoff file.
    """
    return (
        f"Prior claude session for this thread expired "
        f"(age={age_days}d, turns={turn_count}). "
        f"Read {memory_dir}/{thread_id}.md for handoff notes from prior "
        f"sessions before starting fresh."
    )
