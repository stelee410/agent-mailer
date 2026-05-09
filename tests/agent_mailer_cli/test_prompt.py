"""Unit tests for agent_mailer_cli.prompt."""
from __future__ import annotations

from agent_mailer_cli.broker import InboxMessage
from agent_mailer_cli.prompt import FRESH_TEMPLATE, RESUME_TEMPLATE, build_prompt


def _msg() -> InboxMessage:
    return InboxMessage(
        id="msg-001",
        thread_id="thr-XYZ",
        from_agent="pm@example.com",
        to_agent="coder@example.com",
        subject="please ship MVP",
        is_read=False,
        created_at="2026-05-09T05:18:21Z",
        raw={},
    )


def test_fresh_prompt_contains_required_fields() -> None:
    prompt = build_prompt(_msg(), broker_url="https://broker.example.com/", is_resume=False)
    assert "msg-001" in prompt
    assert "thr-XYZ" in prompt
    assert "pm@example.com" in prompt
    assert "please ship MVP" in prompt
    # Trailing slash on broker URL must be stripped — endpoints all start with /.
    assert "https://broker.example.com/messages/msg-001" in prompt
    assert "https://broker.example.com//messages" not in prompt
    # Critical steps from §10.2 fresh template.
    assert "AGENT.md" in prompt
    assert ".agent-mailer/memory/global.md" in prompt
    assert "/messages/thread/thr-XYZ" in prompt
    assert "/messages/send" in prompt
    assert "/read" in prompt


def test_resume_prompt_skips_fresh_intro() -> None:
    prompt = build_prompt(_msg(), broker_url="https://broker.example.com", is_resume=True)
    assert "fresh thread" not in prompt
    assert "active thread" in prompt
    assert ".agent-mailer/memory/thr-XYZ.md" in prompt
    # Don't re-read AGENT.md on resume — context is already loaded.
    assert "Read AGENT.md" not in prompt


def test_template_constants_well_formed() -> None:
    # Spot-check that the templates use named placeholders and don't have stray braces.
    for tmpl in (FRESH_TEMPLATE, RESUME_TEMPLATE):
        assert "{msg_id}" in tmpl
        assert "{thread_id}" in tmpl
        assert "{broker_url}" in tmpl
