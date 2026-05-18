"""Tests for `agent-mailer team init` — deterministic helpers + stubbed-broker e2e."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from agent_mailer_cli import team_setup
from agent_mailer_cli.commands.team_init_cmd import provision_team
from agent_mailer_cli.config import VALID_RUNTIMES, load_config


# ---------- deterministic helpers ----------


def test_valid_runtimes_includes_infiniti() -> None:
    assert "claude" in VALID_RUNTIMES
    assert "codex" in VALID_RUNTIMES
    assert "infiniti" in VALID_RUNTIMES


def test_slugify_team_normalizes_input() -> None:
    assert team_setup.slugify_team("My Team") == "my-team"
    assert team_setup.slugify_team("Foo_Bar.42") == "foo_bar.42"
    assert team_setup.slugify_team("---trailing!!!---") == "trailing"
    assert team_setup.slugify_team("") == ""


def test_is_valid_team_slug_rejects_edges() -> None:
    assert team_setup.is_valid_team_slug("ok")
    assert team_setup.is_valid_team_slug("a")
    assert team_setup.is_valid_team_slug("my-team_42")
    assert not team_setup.is_valid_team_slug("")
    assert not team_setup.is_valid_team_slug("-leading")
    assert not team_setup.is_valid_team_slug("trailing-")
    assert not team_setup.is_valid_team_slug("UPPER")


def test_check_empty_dir_tolerates_allowed_noise(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".DS_Store").write_text("")
    (tmp_path / ".vscode").mkdir()  # PM-approved nice-to-have
    (tmp_path / ".envrc").write_text("")
    team_setup.check_empty_dir(tmp_path)  # no raise


def test_check_empty_dir_rejects_user_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("")
    with pytest.raises(team_setup.TeamSetupError, match="not empty"):
        team_setup.check_empty_dir(tmp_path)


def test_check_empty_dir_rejects_node_modules(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    with pytest.raises(team_setup.TeamSetupError, match="node_modules"):
        team_setup.check_empty_dir(tmp_path)


# ---------- stubbed-broker e2e ----------


def _build_broker_stub(
    *,
    setup_status: int = 200,
    create_status: int = 201,
    capture: list[tuple[str, str, dict]],
) -> httpx.MockTransport:
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else {}
        capture.append((method, path, dict(request.headers), body))
        if method == "POST" and path == "/users/login":
            return httpx.Response(
                200,
                json={
                    "token": "stub-token",
                    "user": {
                        "id": "u1",
                        "username": body.get("username", "stub"),
                        "is_superadmin": False,
                        "created_at": "2026-05-18T00:00:00+00:00",
                    },
                },
            )
        if method == "POST" and path == "/users/me/agents":
            counter["n"] += 1
            name = body["name"]
            return httpx.Response(
                create_status,
                json={
                    "id": f"aid-{counter['n']}",
                    "name": name,
                    "address": f"{name}@stub-user.amp.linkyun.co",
                    "role": body.get("role", ""),
                    "description": body.get("description", ""),
                    "system_prompt": body.get("system_prompt", ""),
                    "tags": [],
                    "team_id": None,
                    "status": "active",
                    "created_at": "2026-05-18T00:00:00+00:00",
                    "last_seen": None,
                    "api_key_masked": "amk_****",
                    "api_key_plaintext": f"key-plain-{counter['n']}",
                },
            )
        if method == "GET" and path.endswith("/setup"):
            if setup_status != 200:
                return httpx.Response(setup_status, json={"detail": "transient hiccup"})
            return httpx.Response(
                200,
                json={
                    "agent_md": "# Agent Identity (stub)\n",
                    "claude_md": "# CLAUDE.md (stub)\n",
                    "infiniti_md": "# INFINITI.md (stub)\n",
                    "instructions": "(stub)",
                },
            )
        raise AssertionError(f"unexpected request: {method} {path}")

    # Capture's 3rd slot stored full headers dict; the test prefers a tuple
    # shape `(method, path, body)` — collapse here.
    def _slim_handler(req: httpx.Request) -> httpx.Response:
        return handler(req)

    return httpx.MockTransport(_slim_handler)


def test_provision_team_writes_full_layout(tmp_path: Path) -> None:
    calls: list[tuple[str, str, dict, dict]] = []
    transport = _build_broker_stub(capture=calls)

    frameworks = {
        "pm": "claude",
        "dev": "codex",
        "reviewer": "claude",
        "support": "infiniti",
    }
    with httpx.Client(transport=transport) as client:
        code = provision_team(
            client,
            tmp_path,
            broker_url="https://stub.example",
            team="smoke",
            frameworks=frameworks,
            username="stub-user",
            password="p@ss",
            permission_mode="acceptEdits",
            project_dir="/work/source",
        )

    assert code == 0

    # 4 create calls + 4 setup fetches, each carrying the right headers.
    create_calls = [c for c in calls if c[1] == "/users/me/agents" and c[0] == "POST"]
    setup_calls = [c for c in calls if c[1].endswith("/setup")]
    assert len(create_calls) == 4
    assert len(setup_calls) == 4
    for c in create_calls:
        assert c[2].get("authorization") == "Bearer stub-token"
    for c in setup_calls:
        # X-API-Key is the agent's own plaintext key, not the user token.
        assert c[2].get("x-api-key", "").startswith("key-plain-")

    for role, framework in frameworks.items():
        role_dir = tmp_path / role
        assert role_dir.is_dir(), f"{role}/ missing"

        cfg = load_config(role_dir)
        assert cfg is not None
        assert cfg.runtime == framework
        assert cfg.agent_id.startswith("aid-")
        assert cfg.api_key.startswith("key-plain-")
        assert cfg.broker_url == "https://stub.example"
        assert cfg.address.startswith(f"smoke-{role}@")
        assert cfg.project_dir == "/work/source"
        assert cfg.permission_mode == "acceptEdits"

        # config.toml must be 0600 on POSIX.
        cfg_file = role_dir / ".agent-mailer" / "config.toml"
        if os.name != "nt":
            mode = stat.S_IMODE(cfg_file.stat().st_mode)
            assert mode == 0o600, f"{role}/config.toml mode {mode:o} != 0600"

        # Identity files branch by runtime.
        if framework == "infiniti":
            assert (role_dir / "SOUL.md").exists()
            assert (role_dir / "INFINITI.md").exists()
            assert not (role_dir / "AGENT.md").exists()
            assert not (role_dir / "CLAUDE.md").exists()
        else:
            assert (role_dir / "AGENT.md").exists()
            assert (role_dir / "CLAUDE.md").exists()
            assert not (role_dir / "SOUL.md").exists()

        # Claude roles MUST ship a .claude/settings.json with the broker
        # allowlist — otherwise headless watch is dead on arrival because
        # claude blocks every curl with "This command requires approval".
        # Codex / infiniti don't need it (codex_runner passes
        # --ask-for-approval never; infiniti CLI has no approval gate).
        claude_settings = role_dir / ".claude" / "settings.json"
        if framework == "claude":
            assert claude_settings.exists(), (
                f"{role}/.claude/settings.json missing for claude runtime"
            )
            settings = json.loads(claude_settings.read_text(encoding="utf-8"))
            allow = settings.get("permissions", {}).get("allow", [])
            assert any("amp.linkyun.co" in pat for pat in allow), (
                f"broker allowlist missing in {claude_settings}: {allow!r}"
            )
            assert any("agent-mailer" in pat for pat in allow), (
                f"agent-mailer allowlist missing in {claude_settings}: {allow!r}"
            )
            assert any(pat.startswith("WebFetch(") for pat in allow), (
                f"WebFetch allowlist missing in {claude_settings}: {allow!r}"
            )
            if os.name != "nt":
                mode = stat.S_IMODE(claude_settings.stat().st_mode)
                assert mode == 0o644, (
                    f"{claude_settings} mode {mode:o} != 0644"
                )
        else:
            assert not claude_settings.exists(), (
                f"{role} runtime={framework} should not ship .claude/settings.json"
            )

        # No leftover partial-setup marker on the success path.
        assert not (role_dir / ".agent-mailer" / "partial_setup_pending").exists()

        # Generated launchers: .sh is 0755, .cmd uses CRLF and %~dp0.
        sh = (tmp_path / f"start-{role}.sh").read_text(encoding="utf-8")
        assert sh.startswith("#!/bin/sh")
        assert f'cd "$DIR/{role}"' in sh
        assert "exec agent-mailer watch" in sh
        if os.name != "nt":
            assert stat.S_IMODE((tmp_path / f"start-{role}.sh").stat().st_mode) == 0o755

        cmd = (tmp_path / f"start-{role}.cmd").read_bytes()
        assert b"\r\n" in cmd
        assert f"%~dp0{role}".encode() in cmd

    meta = json.loads((tmp_path / ".amp-team" / "team.json").read_text())
    assert meta["partial"] is False
    assert meta["team_name"] == "smoke"
    assert len(meta["agents"]) == 4
    assert {a["framework"] for a in meta["agents"]} == {"claude", "codex", "infiniti"}


def test_provision_team_persists_api_key_when_setup_fetch_fails(tmp_path: Path) -> None:
    """v0.1.1 P1-3 regression: /setup 5xx must not orphan the api_key on broker.

    First role (pm) succeeds at create, fails at /setup → we expect:
      - exit code 2
      - pm/.agent-mailer/config.toml exists with api_key persisted
      - pm/.agent-mailer/partial_setup_pending marker present
      - pm/AGENT.md and CLAUDE.md must NOT exist (setup never returned them)
      - team.json reflects partial state with agent metadata
    """
    calls: list[tuple[str, str, dict, dict]] = []
    transport = _build_broker_stub(setup_status=503, capture=calls)

    with httpx.Client(transport=transport) as client:
        code = provision_team(
            client,
            tmp_path,
            broker_url="https://stub.example",
            team="smoke",
            frameworks={r: "claude" for r in team_setup.ROLES},
            username="stub-user",
            password="p@ss",
        )

    assert code == 2, f"expected exit 2 on setup-fetch failure, got {code}"

    cfg = load_config(tmp_path / "pm")
    assert cfg is not None, "config.toml must exist even when setup failed"
    assert cfg.api_key.startswith("key-plain-"), "api_key must be persisted"
    assert cfg.broker_url == "https://stub.example"
    assert cfg.runtime == "claude"

    marker = tmp_path / "pm" / ".agent-mailer" / "partial_setup_pending"
    assert marker.exists(), "partial_setup_pending marker must be set"
    marker_data = json.loads(marker.read_text())
    assert marker_data["role"] == "pm"
    assert marker_data["framework"] == "claude"

    # Identity files must NOT exist — they require successful setup fetch.
    assert not (tmp_path / "pm" / "AGENT.md").exists()
    assert not (tmp_path / "pm" / "CLAUDE.md").exists()

    meta = json.loads((tmp_path / ".amp-team" / "team.json").read_text())
    assert meta["partial"] is True
    assert meta["failure"]["role"] == "pm"
    assert "503" in meta["failure"]["error"]
    assert len(meta["agents"]) == 1
    assert meta["agents"][0]["partial_setup_pending"] is True


def test_provision_team_aborts_on_invalid_credentials(tmp_path: Path) -> None:
    """Login 401 surfaces as exit 4 (distinct from broker-permanent and dir-not-empty)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/login":
            return httpx.Response(401, json={"detail": "Invalid username or password"})
        raise AssertionError(f"should not call beyond login: {request.url.path}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        code = provision_team(
            client,
            tmp_path,
            broker_url="https://stub.example",
            team="smoke",
            frameworks={r: "claude" for r in team_setup.ROLES},
            username="stub-user",
            password="wrong",
        )
    assert code == 4, f"expected exit 4 on invalid login, got {code}"
    # Nothing should have been written.
    assert not (tmp_path / "pm").exists()


def test_write_runtime_settings_claude_writes_broker_allowlist(tmp_path: Path) -> None:
    """v0.2.x P0 regression: claude `acceptEdits` does NOT auto-approve Bash/network,
    so headless watch must ship a `.claude/settings.json` that allow-lists the
    broker URL and the agent-mailer CLI. Without this, every spawned claude
    burns ~$1.50 / ~4min looping on 'This command requires approval' and the
    user gets zero reply — the real bug human hit in production."""
    (tmp_path / "pm").mkdir()
    team_setup.write_runtime_settings(tmp_path, "pm", "claude")

    settings_path = tmp_path / "pm" / ".claude" / "settings.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    allow = data.get("permissions", {}).get("allow", [])
    assert any("amp.linkyun.co" in pat for pat in allow), (
        f"broker URL must be in the allowlist; got {allow!r}"
    )
    assert any("agent-mailer" in pat for pat in allow), (
        f"agent-mailer CLI must be in the allowlist; got {allow!r}"
    )
    # reviewer-driven gap fix: claude may pick WebFetch tool (not Bash curl) for
    # broker GET/POST/PATCH — WebFetch needs its own allow pattern, otherwise
    # we reproduce the same `This command requires approval` hang.
    assert "WebFetch(domain:amp.linkyun.co)" in allow, (
        f"WebFetch(domain:amp.linkyun.co) must be in the allowlist; got {allow!r}"
    )
    if os.name != "nt":
        mode = stat.S_IMODE(settings_path.stat().st_mode)
        assert mode == 0o644, f"settings.json mode {mode:o} != 0644 (it's not a secret)"


def test_write_runtime_settings_skips_non_claude_runtimes(tmp_path: Path) -> None:
    """codex auto-approves via --ask-for-approval never (codex_runner) and the
    infiniti CLI surfaces no approval flag at all — neither needs a
    `.claude/settings.json` (writing one would be misleading)."""
    for framework in ("codex", "infiniti"):
        role = f"r-{framework}"
        (tmp_path / role).mkdir()
        team_setup.write_runtime_settings(tmp_path, role, framework)
        assert not (tmp_path / role / ".claude").exists(), (
            f"runtime={framework} must not create .claude/"
        )


# ---------- infiniti runner ----------


def test_infiniti_runner_build_cmd_matches_cli_help() -> None:
    """`infiniti-agent cli <prompt...>` is the documented non-interactive invocation."""
    from agent_mailer_cli.infiniti_runner import build_cmd

    cmd = build_cmd(infiniti_command="infiniti-agent", prompt="hello world")
    assert cmd == ["infiniti-agent", "cli", "hello world"]


def test_infiniti_runner_ignores_permission_mode_and_session() -> None:
    """Per `infiniti-agent cli --help`: no flag accepts permission_mode or session_id.
    The runner must drop those args without injecting bogus flags."""
    from agent_mailer_cli.infiniti_runner import build_cmd

    cmd = build_cmd(
        infiniti_command="infiniti-agent",
        prompt="x",
        permission_mode="bypassPermissions",
        project_dir="/some/path",
        session_id="should-be-ignored",
    )
    assert cmd == ["infiniti-agent", "cli", "x"]
