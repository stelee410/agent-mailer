"""Tests for Team CRUD, member management, and visibility filtering."""

DOMAIN_SUFFIX = "@testuser.amp.linkyun.co"


async def _register_agent(client, name, role="coder"):
    resp = await client.post("/agents/register", json={
        "name": name, "role": role, "system_prompt": f"I am {name}.",
    })
    assert resp.status_code == 200
    return resp.json()


# --- Team CRUD ---


async def test_create_team(client):
    resp = await client.post("/admin/teams", json={"name": "Alpha", "description": "Alpha team"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alpha"
    assert data["description"] == "Alpha team"
    assert data["agent_count"] == 0
    assert "id" in data


async def test_create_team_no_description(client):
    resp = await client.post("/admin/teams", json={"name": "Beta"})
    assert resp.status_code == 200
    assert resp.json()["description"] == ""


async def test_create_team_duplicate_name(client):
    await client.post("/admin/teams", json={"name": "Dup"})
    resp = await client.post("/admin/teams", json={"name": "Dup"})
    assert resp.status_code == 409


async def test_create_team_empty_name(client):
    resp = await client.post("/admin/teams", json={"name": ""})
    assert resp.status_code == 422


async def test_create_team_name_too_long(client):
    resp = await client.post("/admin/teams", json={"name": "x" * 65})
    assert resp.status_code == 422


async def test_list_teams(client):
    await client.post("/admin/teams", json={"name": "T1"})
    await client.post("/admin/teams", json={"name": "T2"})
    resp = await client.get("/admin/teams")
    assert resp.status_code == 200
    teams = resp.json()
    assert len(teams) == 2
    assert teams[0]["name"] == "T1"
    assert teams[1]["name"] == "T2"


async def test_list_teams_empty(client):
    resp = await client.get("/admin/teams")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_team_detail(client):
    create_resp = await client.post("/admin/teams", json={"name": "Detail", "description": "desc"})
    team_id = create_resp.json()["id"]
    resp = await client.get(f"/admin/teams/{team_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Detail"
    assert data["agents"] == []


async def test_get_team_not_found(client):
    resp = await client.get("/admin/teams/nonexistent-id")
    assert resp.status_code == 404


async def test_update_team(client):
    create_resp = await client.post("/admin/teams", json={"name": "Old"})
    team_id = create_resp.json()["id"]
    resp = await client.put(f"/admin/teams/{team_id}", json={"name": "New", "description": "Updated"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New"
    assert data["description"] == "Updated"


async def test_update_team_partial(client):
    create_resp = await client.post("/admin/teams", json={"name": "Partial", "description": "orig"})
    team_id = create_resp.json()["id"]
    resp = await client.put(f"/admin/teams/{team_id}", json={"description": "changed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Partial"
    assert resp.json()["description"] == "changed"


async def test_update_team_duplicate_name(client):
    await client.post("/admin/teams", json={"name": "Exist"})
    create_resp = await client.post("/admin/teams", json={"name": "Other"})
    team_id = create_resp.json()["id"]
    resp = await client.put(f"/admin/teams/{team_id}", json={"name": "Exist"})
    assert resp.status_code == 409


async def test_update_team_not_found(client):
    resp = await client.put("/admin/teams/fake-id", json={"name": "X"})
    assert resp.status_code == 404


async def test_delete_team(client):
    create_resp = await client.post("/admin/teams", json={"name": "Doomed"})
    team_id = create_resp.json()["id"]
    resp = await client.delete(f"/admin/teams/{team_id}")
    assert resp.status_code == 200

    resp = await client.get(f"/admin/teams/{team_id}")
    assert resp.status_code == 404


async def test_delete_team_not_found(client):
    resp = await client.delete("/admin/teams/fake-id")
    assert resp.status_code == 404


async def test_delete_team_clears_agent_team_id(client):
    agent = await _register_agent(client, "clearer")
    create_resp = await client.post("/admin/teams", json={"name": "ToClear"})
    team_id = create_resp.json()["id"]
    await client.post(f"/admin/teams/{team_id}/agents", json={"agent_id": agent["id"]})

    # Verify agent is in team
    detail = await client.get(f"/admin/teams/{team_id}")
    assert len(detail.json()["agents"]) == 1

    # Delete team
    await client.delete(f"/admin/teams/{team_id}")

    # Verify agent's team_id is cleared
    resp = await client.get(f"/agents/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["team_id"] is None


# --- Member management ---


async def test_add_agent_to_team(client):
    agent = await _register_agent(client, "member1")
    create_resp = await client.post("/admin/teams", json={"name": "Squad"})
    team_id = create_resp.json()["id"]

    resp = await client.post(f"/admin/teams/{team_id}/agents", json={"agent_id": agent["id"]})
    assert resp.status_code == 200

    detail = await client.get(f"/admin/teams/{team_id}")
    assert len(detail.json()["agents"]) == 1
    assert detail.json()["agents"][0]["id"] == agent["id"]


async def test_add_agent_already_in_other_team(client):
    agent = await _register_agent(client, "conflict-agent")
    t1 = (await client.post("/admin/teams", json={"name": "Team1"})).json()["id"]
    t2 = (await client.post("/admin/teams", json={"name": "Team2"})).json()["id"]

    await client.post(f"/admin/teams/{t1}/agents", json={"agent_id": agent["id"]})
    resp = await client.post(f"/admin/teams/{t2}/agents", json={"agent_id": agent["id"]})
    assert resp.status_code == 409


async def test_add_agent_not_found(client):
    t = (await client.post("/admin/teams", json={"name": "T"})).json()["id"]
    resp = await client.post(f"/admin/teams/{t}/agents", json={"agent_id": "fake-id"})
    assert resp.status_code == 404


async def test_add_agent_team_not_found(client):
    agent = await _register_agent(client, "orphan")
    resp = await client.post("/admin/teams/fake-id/agents", json={"agent_id": agent["id"]})
    assert resp.status_code == 404


async def test_remove_agent_from_team(client):
    agent = await _register_agent(client, "remover")
    t = (await client.post("/admin/teams", json={"name": "RemTeam"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": agent["id"]})

    resp = await client.delete(f"/admin/teams/{t}/agents/{agent['id']}")
    assert resp.status_code == 200

    detail = await client.get(f"/admin/teams/{t}")
    assert len(detail.json()["agents"]) == 0


async def test_remove_agent_not_in_team(client):
    agent = await _register_agent(client, "notin")
    t = (await client.post("/admin/teams", json={"name": "NoIn"})).json()["id"]
    resp = await client.delete(f"/admin/teams/{t}/agents/{agent['id']}")
    assert resp.status_code == 404


async def test_list_teams_shows_agent_count(client):
    agent1 = await _register_agent(client, "count1")
    agent2 = await _register_agent(client, "count2")
    t = (await client.post("/admin/teams", json={"name": "Counted"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": agent1["id"]})
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": agent2["id"]})

    teams = (await client.get("/admin/teams")).json()
    team = [x for x in teams if x["id"] == t][0]
    assert team["agent_count"] == 2


# --- Visibility filtering ---


async def test_visibility_same_team(client):
    a1 = await _register_agent(client, "vis-a1")
    a2 = await _register_agent(client, "vis-a2")
    a3 = await _register_agent(client, "vis-a3")

    t = (await client.post("/admin/teams", json={"name": "VisTeam"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": a1["id"]})
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": a2["id"]})
    # a3 is not in any team

    # a1 should see a2 (same team) but not a3 (ungrouped)
    resp = await client.get(f"/agents?agent_id={a1['id']}")
    assert resp.status_code == 200
    addresses = {a["address"] for a in resp.json()}
    assert a2["address"] in addresses
    assert a1["address"] in addresses
    assert a3["address"] not in addresses


async def test_visibility_ungrouped(client):
    a1 = await _register_agent(client, "ung-a1")
    a2 = await _register_agent(client, "ung-a2")
    a3 = await _register_agent(client, "ung-a3")

    t = (await client.post("/admin/teams", json={"name": "UngTeam"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": a3["id"]})
    # a1 and a2 are ungrouped, a3 is in a team

    # a1 (ungrouped) should see a2 (also ungrouped) but not a3 (in team)
    resp = await client.get(f"/agents?agent_id={a1['id']}")
    addresses = {a["address"] for a in resp.json()}
    assert a2["address"] in addresses
    assert a1["address"] in addresses
    assert a3["address"] not in addresses


async def test_visibility_human_operator_always_visible(client):
    # Ensure human operator exists
    await client.get("/admin/human-operator")

    a1 = await _register_agent(client, "hop-a1")
    t = (await client.post("/admin/teams", json={"name": "HopTeam"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": a1["id"]})

    resp = await client.get(f"/agents?agent_id={a1['id']}")
    roles = {a["role"] for a in resp.json()}
    assert "operator" in roles


async def test_visibility_no_agent_id_returns_all(client):
    a1 = await _register_agent(client, "all-a1")
    a2 = await _register_agent(client, "all-a2")

    t = (await client.post("/admin/teams", json={"name": "AllTeam"})).json()["id"]
    await client.post(f"/admin/teams/{t}/agents", json={"agent_id": a1["id"]})

    # Without agent_id, should return all agents (backward compat)
    resp = await client.get("/agents")
    addresses = {a["address"] for a in resp.json()}
    assert a1["address"] in addresses
    assert a2["address"] in addresses


async def test_visibility_agent_not_found(client):
    resp = await client.get("/agents?agent_id=fake-id")
    assert resp.status_code == 404


# --- /admin/teams/bootstrap ---


async def test_bootstrap_team_happy_path(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "BootSquad",
        "description": "demo team",
        "agents": [
            {"name": "planner", "role": "planner", "system_prompt": "I plan."},
            {"name": "coder", "role": "coder", "system_prompt": "I code."},
            {"name": "reviewer", "role": "reviewer", "system_prompt": "I review."},
        ],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["team"]["name"] == "BootSquad"
    assert body["team"]["agent_count"] == 3
    assert len(body["agents"]) == 3

    by_name = {a["name"]: a for a in body["agents"]}
    assert set(by_name) == {"planner", "coder", "reviewer"}

    for name, agent in by_name.items():
        assert agent["address"] == f"{name}{DOMAIN_SUFFIX}"
        assert agent["api_key_plaintext"].startswith("amk_")
        # AGENT.md should use env-var placeholder, not the inline one.
        assert "${AMP_API_KEY}" in agent["agent_md"]
        assert "<your_api_key>" not in agent["agent_md"]
        assert agent["address"] in agent["agent_md"]
        assert agent["agent_id"] in agent["agent_md"]

    # Agents should actually be attached to the team.
    detail = await client.get(f"/admin/teams/{body['team']['id']}")
    assert detail.status_code == 200
    detail_agents = {a["name"] for a in detail.json()["agents"]}
    assert detail_agents == {"planner", "coder", "reviewer"}


async def test_bootstrap_team_address_local_override(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "OverrideSquad",
        "agents": [
            {"name": "Planner Bot", "address_local": "planner-1", "system_prompt": "."},
        ],
    })
    assert resp.status_code == 200
    addr = resp.json()["agents"][0]["address"]
    assert addr == f"planner-1{DOMAIN_SUFFIX}"


async def test_bootstrap_team_requires_at_least_one_agent(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "Empty", "agents": [],
    })
    assert resp.status_code == 422


async def test_bootstrap_team_duplicate_local_in_request(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "DupLocal",
        "agents": [
            {"name": "a", "address_local": "shared", "system_prompt": "."},
            {"name": "b", "address_local": "shared", "system_prompt": "."},
        ],
    })
    assert resp.status_code == 400
    assert "shared" in resp.json()["detail"]


async def test_bootstrap_team_invalid_local_part(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "BadLocal",
        "agents": [{"name": "ok", "address_local": "_bad_", "system_prompt": "."}],
    })
    assert resp.status_code == 400


async def test_bootstrap_team_name_collision(client):
    await client.post("/admin/teams", json={"name": "Existing"})
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "Existing",
        "agents": [{"name": "x", "system_prompt": "."}],
    })
    assert resp.status_code == 409


async def test_bootstrap_team_address_collision_is_atomic(client):
    # Pre-create an agent that will collide with one of the bootstrap entries.
    await _register_agent(client, "planner")

    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "WillFail",
        "agents": [
            {"name": "coder", "system_prompt": "."},
            {"name": "planner", "system_prompt": "."},  # collides
        ],
    })
    assert resp.status_code == 409

    # Atomicity: no team created, no "coder" agent created either.
    teams = (await client.get("/admin/teams")).json()
    assert "WillFail" not in {t["name"] for t in teams}

    agents_resp = await client.get("/agents")
    addresses = {a["address"] for a in agents_resp.json()}
    assert f"coder{DOMAIN_SUFFIX}" not in addresses


async def test_bootstrap_team_api_keys_actually_work(client):
    resp = await client.post("/admin/teams/bootstrap", json={
        "name": "WorkingKeys",
        "agents": [{"name": "live", "role": "coder", "system_prompt": "."}],
    })
    assert resp.status_code == 200
    agent = resp.json()["agents"][0]

    # The freshly-issued API key should authenticate the agent against its mailbox.
    inbox = await client.get(
        f"/messages/inbox/{agent['address']}?agent_id={agent['agent_id']}",
        headers={"X-API-Key": agent["api_key_plaintext"]},
    )
    assert inbox.status_code == 200
