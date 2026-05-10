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
    assert "init" in result.output
    assert "start" in result.output
    assert "stop" in result.output


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

    assert ("POST", "/admin/teams") in requests
    assert requests.count(("POST", "/users/me/agents")) == 4


def test_run_script_missing_exits(tmp_path: Path) -> None:
    with pytest.raises(click.ClickException) as exc:
        amp._run_script(tmp_path, "start-team.sh")
    assert "amp init" in str(exc.value)
