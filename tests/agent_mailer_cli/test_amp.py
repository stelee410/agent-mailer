from __future__ import annotations

import json
import tomllib
from pathlib import Path

import click
import httpx
import pytest
from click.testing import CliRunner

from agent_mailer_cli import amp
from agent_mailer_cli.config import load_config


def test_pyproject_exposes_amp_script() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text())
    scripts = data["project"]["scripts"]
    assert scripts["agent-mailer"] == "agent_mailer_cli.main:cli"
    assert scripts["amp"] == "agent_mailer_cli.amp:cli"


def test_amp_help_shows_short_commands() -> None:
    result = CliRunner().invoke(amp.cli, ["--help"])
    assert result.exit_code == 0
    assert "claude-code" in result.output
    assert "codex" in result.output
    assert "init" in result.output
    assert "login" in result.output
    assert "start" in result.output
    assert "stop" in result.output
    assert "up" in result.output


def test_normalize_team_name() -> None:
    assert amp.normalize_team_name("Demo Team!") == "demo-team"
    assert amp.normalize_team_name("__") == "team"
    assert amp.normalize_team_name("-bad") == "bad"


def test_render_team_yaml_default_agents() -> None:
    text = amp.render_team_yaml("demo", "http://broker.test", "acceptEdits")
    assert "team: demo" in text
    assert "broker_url: http://broker.test" in text
    for name in ("demo_planner", "demo_coder", "demo_reviewer", "demo_runner"):
        assert f"name: {name}" in text
    assert "forward 给 demo_coder" in text
    assert "reply 给 demo_reviewer" in text


def test_resolve_broker_url_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMP_BROKER_URL", "http://env-broker.test/")
    creds = {"default_broker_url": "http://saved-broker.test"}
    assert amp._resolve_broker_url(None, creds) == "http://env-broker.test"


def test_resolve_target_dir_from_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMP_TEAMS_DIR", str(tmp_path))
    assert amp._resolve_target_dir("Demo Team!", None) == tmp_path / "demo-team"
    assert amp._resolve_team_name("Demo Team!", None, tmp_path / "demo-team") == "demo-team"


def test_resolve_target_dir_from_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AMP_TEAMS_DIR", str(tmp_path / "teams"))
    target = tmp_path / "nested" / "ops"
    assert amp._resolve_target_dir("nested/ops", None) == target
    assert amp._resolve_team_name("nested/ops", None, target) == "ops"


def test_runtime_shortcut_names_add_clear_suffixes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "Agent Mailer"
    project.mkdir()
    monkeypatch.chdir(project)

    assert amp._runtime_command_target(None, "codex") == ("agent-mailer-codex", "agent-mailer-codex")
    assert amp._runtime_command_target("Agent-Mailer-CodeX", "codex") == (
        "agent-mailer-codex",
        "agent-mailer-codex",
    )
    assert amp._runtime_command_target("agent-mailer", "claude") == (
        "agent-mailer-claude-code",
        "agent-mailer-claude-code",
    )
    assert amp._runtime_command_target("./teams/agent-mailer", "codex") == (
        "./teams/agent-mailer",
        "agent-mailer-codex",
    )


def test_command_hint_matches_named_team() -> None:
    assert amp._command_with_target("start", "demo", None) == "amp start demo"
    assert amp._command_with_target("stop", None, Path("/tmp/demo")) == "amp stop --dir /tmp/demo"
    assert amp._command_with_target("start", None, None) == "amp start"


def test_start_accepts_named_team_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, str]] = []

    def fake_run_script(out_dir: Path, name: str) -> None:
        calls.append((out_dir, name))

    monkeypatch.setenv("AMP_TEAMS_DIR", str(tmp_path))
    monkeypatch.setattr(amp, "_run_script", fake_run_script)

    result = CliRunner().invoke(amp.cli, ["start", "Demo Team!"])

    assert result.exit_code == 0
    assert calls == [(tmp_path / "demo-team", "start-team.sh")]


def test_stop_without_name_uses_last_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, str]] = []

    def fake_run_script(out_dir: Path, name: str) -> None:
        calls.append((out_dir, name))

    target = tmp_path / "agent-mailer-codex"
    monkeypatch.setenv("AMP_STATE_PATH", str(tmp_path / "amp-state.json"))
    amp._save_last_team(target, "agent-mailer-codex")
    monkeypatch.setattr(amp, "_run_script", fake_run_script)

    result = CliRunner().invoke(amp.cli, ["stop"])

    assert result.exit_code == 0
    assert calls == [(target.resolve(), "stop-team.sh")]


def test_codex_shortcut_creates_suffixed_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "Agent Mailer"
    project.mkdir()
    monkeypatch.chdir(project)
    captured: dict[str, object] = {}
    calls: list[tuple[Path, str]] = []
    remembered: list[tuple[Path, str]] = []
    target = tmp_path / "teams" / "agent-mailer-codex"

    def fake_initialize_team(**kwargs: object) -> tuple[Path, str, str, str, list[dict[str, str]]]:
        captured.update(kwargs)
        return (
            target,
            str(kwargs["team"]),
            "http://broker.test",
            "fanjingwen",
            [{"name": "agent-mailer-codex_planner", "address": "planner@example.test"}],
        )

    def fake_save_last_team(out_dir: Path, team_name: str) -> None:
        remembered.append((out_dir, team_name))

    def fake_run_script(out_dir: Path, name: str) -> None:
        calls.append((out_dir, name))

    monkeypatch.setattr(amp, "_initialize_team", fake_initialize_team)
    monkeypatch.setattr(amp, "_save_last_team", fake_save_last_team)
    monkeypatch.setattr(amp, "_run_script", fake_run_script)

    result = CliRunner().invoke(amp.cli, ["codex"])

    assert result.exit_code == 0
    assert captured["name"] == "agent-mailer-codex"
    assert captured["team"] == "agent-mailer-codex"
    assert captured["runtime"] == "codex"
    assert remembered == [(target, "agent-mailer-codex")]
    assert calls == [(target, "start-team.sh")]
    assert "Start: amp start" in result.output
    assert "Stop:  amp stop" in result.output


def test_create_default_team_writes_agent_workdirs(tmp_path: Path) -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/admin/teams":
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path == "/admin/teams":
            return httpx.Response(200, json={"id": "team-1", "name": "demo"})
        if request.method == "GET" and request.url.path == "/users/me/agents":
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path == "/users/me/agents":
            body = json.loads(request.content)
            name = body["name"]
            return httpx.Response(
                201,
                json={
                    "id": f"id-{name}",
                    "name": name,
                    "address": f"{name}@alice.amp.linkyun.co",
                    "role": body["role"],
                    "description": body["description"],
                    "system_prompt": body["system_prompt"],
                    "tags": [],
                    "team_id": "team-1",
                    "status": "active",
                    "created_at": "2026-05-10T00:00:00+00:00",
                    "last_seen": None,
                    "api_key_masked": "amk_****",
                    "api_key_plaintext": f"amk-{name}",
                },
            )
        if request.method == "GET" and request.url.path.endswith("/export"):
            agent_id = request.url.path.split("/")[-2]
            return httpx.Response(200, json={"filename": "AGENT.md", "content": f"# {agent_id}\n"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        agents = amp.create_default_team(
            out_dir=tmp_path,
            team="demo",
            broker_url="http://broker.test",
            token="session-token",
            permission_mode="acceptEdits",
            runtime="codex",
            client=client,
        )

    assert [a["name"] for a in agents] == [
        "demo_planner",
        "demo_coder",
        "demo_reviewer",
        "demo_runner",
    ]
    assert (tmp_path / "team.yaml").exists()
    assert (tmp_path / "start-team.sh").exists()
    assert (tmp_path / "stop-team.sh").exists()
    assert "agents/" in (tmp_path / ".gitignore").read_text()

    for agent in agents:
        agent_dir = tmp_path / "agents" / agent["name"]
        assert (agent_dir / "AGENT.md").read_text().startswith("# id-")
        cfg = load_config(agent_dir)
        assert cfg is not None
        assert cfg.agent_name == agent["name"]
        assert cfg.broker_url == "http://broker.test"
        assert cfg.api_key == f"amk-{agent['name']}"
        assert cfg.permission_mode == "acceptEdits"
        assert cfg.runtime == "codex"

    assert ("POST", "/admin/teams") in requests
    assert requests.count(("POST", "/users/me/agents")) == 4


def test_run_script_missing_exits(tmp_path: Path) -> None:
    with pytest.raises(click.ClickException) as exc:
        amp._run_script(tmp_path, "start-team.sh")
    assert "amp init" in str(exc.value)
