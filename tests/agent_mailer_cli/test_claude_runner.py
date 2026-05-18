"""build_cmd shape tests for claude_runner.

v0.2.x human override: when permission_mode == "bypassPermissions" the runner
emits `--dangerously-skip-permissions` instead of `--permission-mode
bypassPermissions`, so headless `-p` mode fully auto-runs without per-tool
approval prompts. Other modes keep the original `--permission-mode <value>`
flag verbatim.
"""
from agent_mailer_cli.claude_runner import build_cmd


def _flags(cmd: list[str]) -> list[str]:
    return [tok for tok in cmd if tok.startswith("--")]


def test_build_cmd_bypass_uses_dangerously_skip_permissions() -> None:
    cmd = build_cmd(
        claude_command="claude",
        prompt="hi",
        permission_mode="bypassPermissions",
    )
    assert "--dangerously-skip-permissions" in cmd
    # bypassPermissions IS the skip flag — `--permission-mode` must not be
    # emitted alongside it (claude would reject conflicting permission flags).
    assert "--permission-mode" not in cmd
    assert "bypassPermissions" not in cmd


def test_build_cmd_accept_edits_keeps_permission_mode_flag() -> None:
    cmd = build_cmd(
        claude_command="claude",
        prompt="hi",
        permission_mode="acceptEdits",
    )
    assert "--permission-mode" in cmd
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_plan_keeps_permission_mode_flag() -> None:
    cmd = build_cmd(
        claude_command="claude",
        prompt="hi",
        permission_mode="plan",
    )
    assert "--permission-mode" in cmd
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "plan"
    assert "--dangerously-skip-permissions" not in cmd


def test_build_cmd_bypass_with_session_id_appends_resume() -> None:
    cmd = build_cmd(
        claude_command="claude",
        prompt="hi",
        permission_mode="bypassPermissions",
        session_id="sess-123",
    )
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[-2:] == ["--resume", "sess-123"]


def test_build_cmd_preserves_prompt_and_json_output() -> None:
    """Regression: the runner still ships `-p <prompt> --output-format json`."""
    cmd = build_cmd(
        claude_command="claude",
        prompt="hello world",
        permission_mode="bypassPermissions",
    )
    assert cmd[:5] == ["claude", "-p", "hello world", "--output-format", "json"]
