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
