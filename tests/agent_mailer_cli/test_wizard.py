"""Tests for the permission_mode wizard prompt (SPEC §15.6 invariant #8).

Reviewer-mandated coverage (M2 review P1-2):
  • empty input must NOT silently default to acceptEdits
  • Scenario B (current="plan") + Enter must NOT escalate to acceptEdits
  • explicit 1/2/3 selection still works
  • --no-interactive without permission_mode aborts cleanly
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from agent_mailer_cli.config import VALID_PERMISSION_MODES
from agent_mailer_cli.wizard import WizardAborted, _resolve_permission_mode


class _ScriptedPrompt:
    """Drive `_resolve_permission_mode` by patching click.prompt."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.errors: list[str] = []

    def __call__(self, *args, **kwargs):  # noqa: ANN001 — match click.prompt signature
        if not self.replies:
            raise AssertionError("ran out of scripted replies — prompt looped beyond test setup")
        return self.replies.pop(0)


def _patch_prompt(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> _ScriptedPrompt:
    fake = _ScriptedPrompt(replies)
    monkeypatch.setattr("agent_mailer_cli.wizard.click.prompt", fake)
    return fake


def test_explicit_1_returns_accept_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_prompt(monkeypatch, ["1"])
    assert _resolve_permission_mode({}, no_interactive=False) == "acceptEdits"
    assert fake.replies == []


def test_explicit_3_returns_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["3"])
    assert _resolve_permission_mode({}, no_interactive=False) == "plan"


def test_word_form_returns_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["bypassPermissions"])
    assert _resolve_permission_mode({}, no_interactive=False) == "bypassPermissions"


def test_empty_input_reprompts_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §15.6 #8 / §8.3: empty input MUST NOT be silently accepted."""
    fake = _patch_prompt(monkeypatch, ["", "", "2"])
    result = _resolve_permission_mode({}, no_interactive=False)
    assert result == "bypassPermissions"
    # All three replies were consumed — confirms the loop didn't short-circuit.
    assert fake.replies == []


def test_invalid_then_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_prompt(monkeypatch, ["x", "9", "1"])
    assert _resolve_permission_mode({}, no_interactive=False) == "acceptEdits"


def test_scenario_b_plan_current_no_silent_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Critical regression test (P1-2): a user on a 'plan' (read-only) workdir
    must NEVER have their permission silently widened by hitting Enter."""
    fake = _patch_prompt(monkeypatch, ["", "", "3"])  # press Enter twice, then deliberately pick plan again
    result = _resolve_permission_mode({}, no_interactive=False, current="plan")
    assert result == "plan"
    # Confirm the wizard never took an early exit.
    assert fake.replies == []
    # And confirm it never returned acceptEdits silently.
    assert result != "acceptEdits"


def test_no_interactive_with_existing_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """If permission_mode is already set in config, --no-interactive accepts it."""
    # Patch prompt to blow up if called — proves no interactive prompting happens.
    monkeypatch.setattr("agent_mailer_cli.wizard.click.prompt",
                        lambda *a, **kw: pytest.fail("should not prompt in --no-interactive"))
    assert _resolve_permission_mode({}, no_interactive=True, current="plan") == "plan"


def test_no_interactive_without_value_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_mailer_cli.wizard.click.prompt",
                        lambda *a, **kw: pytest.fail("should not prompt in --no-interactive"))
    with pytest.raises(WizardAborted):
        _resolve_permission_mode({}, no_interactive=True)


def test_cli_override_short_circuits_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_mailer_cli.wizard.click.prompt",
                        lambda *a, **kw: pytest.fail("should not prompt when CLI provides value"))
    result = _resolve_permission_mode(
        {"permission_mode": "bypassPermissions"}, no_interactive=False,
    )
    assert result == "bypassPermissions"
    assert result in VALID_PERMISSION_MODES
