from __future__ import annotations

from agent_mailer_cli.codex_runner import build_cmd, parse_codex_output


def test_build_cmd_fresh_workspace_write() -> None:
    cmd = build_cmd(
        codex_command="codex",
        prompt="do work",
        permission_mode="acceptEdits",
    )
    assert cmd == [
        "codex",
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "do work",
    ]


def test_build_cmd_resume_read_only() -> None:
    cmd = build_cmd(
        codex_command="codex",
        prompt="continue",
        permission_mode="plan",
        session_id="session-1",
    )
    assert cmd == [
        "codex",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "exec",
        "resume",
        "--json",
        "--skip-git-repo-check",
        "session-1",
        "continue",
    ]


def test_build_cmd_bypass() -> None:
    cmd = build_cmd(
        codex_command="codex",
        prompt="do work",
        permission_mode="bypassPermissions",
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--sandbox" not in cmd


def test_parse_codex_output_finds_nested_session_id() -> None:
    parsed, err = parse_codex_output(
        '{"type":"event","payload":{"session_id":"abc-123"}}\n'
        '{"type":"done"}\n'
    )
    assert err is None
    assert parsed is not None
    assert parsed["session_id"] == "abc-123"
    assert parsed["events"] == 2


def test_parse_codex_output_rejects_non_jsonl() -> None:
    parsed, err = parse_codex_output("not json\n")
    assert parsed is None
    assert err is not None
    assert "JSONL" in err
