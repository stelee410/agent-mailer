"""Self-service `/users/me/agents/*` CRUD: permission and team boundaries.

Each test sets up two distinct users and asserts owner can / non-owner
can't. Admin (superadmin) is verified separately to keep seeing every
agent through the original ``/superadmin/agents`` view.
"""

import os

os.environ.setdefault(
    "AGENT_MAILER_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-bytes-long",
)

import pytest
from httpx import ASGITransport, AsyncClient

from agent_mailer.bootstrap import ensure_bootstrap_invite_code
from agent_mailer.db import get_db, init_db
from agent_mailer.main import app


@pytest.fixture
async def client():
    db = await get_db(":memory:")
    await init_db(db)
    app.state.db = db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await db.close()


@pytest.fixture
async def two_users(client):
    """Bootstrap → register superadmin (admin) and a second normal user (alice)."""
    db = client._transport.app.state.db  # noqa
    code = await ensure_bootstrap_invite_code(db)
    # First user becomes superadmin.
    await client.post(
        "/users/register",
        json={
            "username": "admin",
            "password": "admin-password-123",
            "invite_code": code,
        },
    )
    r = await client.post(
        "/users/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    admin_token = r.json()["token"]
    admin_h = {"Authorization": f"Bearer {admin_token}"}

    # Issue an invite code as superadmin so a regular second user can register.
    r = await client.post("/superadmin/invite-codes", headers=admin_h)
    invite_alice = r.json()["code"]
    await client.post(
        "/users/register",
        json={
            "username": "alice",
            "password": "alice-password-123",
            "invite_code": invite_alice,
        },
    )
    r = await client.post(
        "/users/login",
        json={"username": "alice", "password": "alice-password-123"},
    )
    alice_token = r.json()["token"]
    alice_h = {"Authorization": f"Bearer {alice_token}"}

    # Bob too, so cross-user isolation has somewhere to fail.
    r = await client.post("/superadmin/invite-codes", headers=admin_h)
    invite_bob = r.json()["code"]
    await client.post(
        "/users/register",
        json={
            "username": "bob",
            "password": "bob-password-123",
            "invite_code": invite_bob,
        },
    )
    r = await client.post(
        "/users/login",
        json={"username": "bob", "password": "bob-password-123"},
    )
    bob_token = r.json()["token"]
    bob_h = {"Authorization": f"Bearer {bob_token}"}

    return {
        "admin": admin_h,
        "alice": alice_h,
        "bob": bob_h,
    }


# --- Create / list / read ---


async def test_user_can_create_own_agent(client, two_users):
    r = await client.post(
        "/users/me/agents",
        json={"name": "alpha", "role": "coder", "system_prompt": "hi"},
        headers=two_users["alice"],
    )
    assert r.status_code == 201
    body = r.json()
    assert body["address"] == "alpha@alice.amp.linkyun.co"
    assert body["api_key_plaintext"].startswith("amk_")
    assert body["api_key_masked"].startswith("amk_****")


async def test_user_can_list_own_agents(client, two_users):
    await client.post("/users/me/agents", json={"name": "a1"}, headers=two_users["alice"])
    await client.post("/users/me/agents", json={"name": "a2"}, headers=two_users["alice"])
    r = await client.get("/users/me/agents", headers=two_users["alice"])
    assert r.status_code == 200
    names = sorted(a["name"] for a in r.json())
    assert names == ["a1", "a2"]


async def test_user_cannot_list_other_users_agents(client, two_users):
    await client.post("/users/me/agents", json={"name": "alice-only"}, headers=two_users["alice"])
    r = await client.get("/users/me/agents", headers=two_users["bob"])
    assert r.status_code == 200
    assert r.json() == []  # Bob sees nothing of Alice's


async def test_user_can_get_own_agent_by_id(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "xx"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.get(f"/users/me/agents/{aid}", headers=two_users["alice"])
    assert r.status_code == 200
    assert r.json()["name"] == "xx"


async def test_user_cannot_get_other_users_agent_by_id(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "private"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.get(f"/users/me/agents/{aid}", headers=two_users["bob"])
    # 404, not 403 — don't leak existence.
    assert r.status_code == 404


# --- Edit / delete ---


async def test_user_can_edit_own_agent(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "edit-me"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.put(
        f"/users/me/agents/{aid}",
        json={"role": "reviewer", "tags": ["p1"]},
        headers=two_users["alice"],
    )
    assert r.status_code == 200
    assert r.json()["role"] == "reviewer"
    assert r.json()["tags"] == ["p1"]


async def test_user_cannot_edit_other_users_agent(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "p"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.put(
        f"/users/me/agents/{aid}",
        json={"role": "hijacked"},
        headers=two_users["bob"],
    )
    assert r.status_code == 404


async def test_user_can_delete_own_agent(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "del-me"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.delete(f"/users/me/agents/{aid}", headers=two_users["alice"])
    assert r.status_code == 200

    # Default list excludes soft-deleted.
    r = await client.get("/users/me/agents", headers=two_users["alice"])
    assert all(a["id"] != aid for a in r.json())

    # include_deleted=true brings it back with status='deleted'.
    r = await client.get("/users/me/agents?include_deleted=true", headers=two_users["alice"])
    assert any(a["id"] == aid and a["status"] == "deleted" for a in r.json())


async def test_user_cannot_delete_other_users_agent(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "safe"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.delete(f"/users/me/agents/{aid}", headers=two_users["bob"])
    assert r.status_code == 404


# --- Regenerate / export ---


async def test_user_can_regenerate_own_agent_key(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "rot"}, headers=two_users["alice"])
    aid = r.json()["id"]
    old_key = r.json()["api_key_plaintext"]

    # Old key works through the public /agents endpoint.
    r = await client.get("/agents", headers={"X-API-Key": old_key})
    assert r.status_code == 200

    r = await client.post(
        f"/users/me/agents/{aid}/regenerate-key", headers=two_users["alice"]
    )
    assert r.status_code == 200
    new_key = r.json()["api_key_plaintext"]
    assert new_key != old_key

    # Old key revoked.
    r_old = await client.get("/agents", headers={"X-API-Key": old_key})
    assert r_old.status_code == 401
    r_new = await client.get("/agents", headers={"X-API-Key": new_key})
    assert r_new.status_code == 200


async def test_user_cannot_regenerate_other_users_agent_key(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "x"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.post(
        f"/users/me/agents/{aid}/regenerate-key", headers=two_users["bob"]
    )
    assert r.status_code == 404


async def test_user_can_export_own_agent_md(client, two_users):
    r = await client.post(
        "/users/me/agents",
        json={"name": "exp", "system_prompt": "exp prompt"},
        headers=two_users["alice"],
    )
    aid = r.json()["id"]
    r = await client.get(
        f"/users/me/agents/{aid}/export?format=agent_md", headers=two_users["alice"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "AGENT.md"
    assert "exp prompt" in body["content"]
    assert "<your_api_key>" in body["content"]
    # Security note must mention the user namespace, not @admin.
    assert "@alice.amp.linkyun.co" in body["content"]
    assert "@admin." not in body["content"]


async def test_user_cannot_export_other_users_agent_md(client, two_users):
    r = await client.post("/users/me/agents", json={"name": "secret"}, headers=two_users["alice"])
    aid = r.json()["id"]
    r = await client.get(
        f"/users/me/agents/{aid}/export?format=agent_md", headers=two_users["bob"]
    )
    assert r.status_code == 404


# --- Team membership enforcement ---


async def test_user_team_id_must_be_in_user_teams(client, two_users):
    # Alice creates her team.
    r = await client.post(
        "/admin/teams",
        json={"name": "alice-team", "description": ""},
        headers=two_users["alice"],
    )
    alice_team_id = r.json()["id"]
    # Bob creates his team.
    r = await client.post(
        "/admin/teams",
        json={"name": "bob-team", "description": ""},
        headers=two_users["bob"],
    )
    bob_team_id = r.json()["id"]

    # Alice creating an agent with her own team — OK.
    r = await client.post(
        "/users/me/agents",
        json={"name": "ok", "team_id": alice_team_id},
        headers=two_users["alice"],
    )
    assert r.status_code == 201
    own_agent_id = r.json()["id"]

    # Alice creating an agent under Bob's team — rejected with 400.
    r = await client.post(
        "/users/me/agents",
        json={"name": "stolen", "team_id": bob_team_id},
        headers=two_users["alice"],
    )
    assert r.status_code == 400
    assert "team" in r.json()["detail"].lower()

    # Editing into Bob's team also rejected.
    r = await client.put(
        f"/users/me/agents/{own_agent_id}",
        json={"team_id": bob_team_id},
        headers=two_users["alice"],
    )
    assert r.status_code == 400


async def test_user_team_id_can_be_unset_to_null(client, two_users):
    r = await client.post(
        "/admin/teams",
        json={"name": "t", "description": ""},
        headers=two_users["alice"],
    )
    team_id = r.json()["id"]
    r = await client.post(
        "/users/me/agents",
        json={"name": "a", "team_id": team_id},
        headers=two_users["alice"],
    )
    aid = r.json()["id"]
    # Empty string resets to NULL via the existing `or None` coercion.
    r = await client.put(
        f"/users/me/agents/{aid}", json={"team_id": ""}, headers=two_users["alice"]
    )
    assert r.status_code == 200
    assert r.json()["team_id"] is None


# --- Cross-namespace bookkeeping ---


async def test_admin_and_user_namespaces_dont_pollute_each_other(client, two_users):
    """Admin namespace and per-user namespace are isolated by design.

    The superadmin's ``/superadmin/agents`` view shows only what the
    admin themselves created; user-created agents do NOT show up there.
    Symmetrically, a user's ``/users/me/agents`` shows only their own,
    never agents the admin created. The intended cross-tenant view for
    superadmins is the existing ``/superadmin/users`` + login-as
    impersonation flow — not a global agents listing.

    This test is the regression guard for that isolation: introducing
    ``/users/me/agents`` (FEAT4) must not leak in either direction.
    """
    # Alice creates an agent.
    await client.post(
        "/users/me/agents", json={"name": "alice-only"}, headers=two_users["alice"]
    )
    # Admin creates one of their own.
    await client.post(
        "/superadmin/agents", json={"name": "admin-only"}, headers=two_users["admin"]
    )

    # Admin's /superadmin/agents shows admin-only.
    r = await client.get("/superadmin/agents", headers=two_users["admin"])
    assert r.status_code == 200
    names = [a["name"] for a in r.json()]
    assert "admin-only" in names
    # Alice's agent does not pollute the admin's namespace.
    assert "alice-only" not in names

    # Alice's /users/me/agents shows her own only.
    r = await client.get("/users/me/agents", headers=two_users["alice"])
    names = [a["name"] for a in r.json()]
    assert names == ["alice-only"]


async def test_user_cannot_reach_superadmin_agents_endpoints(client, two_users):
    assert (
        await client.get("/superadmin/agents", headers=two_users["alice"])
    ).status_code == 403
    assert (
        await client.post(
            "/superadmin/agents", json={"name": "x"}, headers=two_users["alice"]
        )
    ).status_code == 403


async def test_user_address_collision_409(client, two_users):
    await client.post("/users/me/agents", json={"name": "dup"}, headers=two_users["alice"])
    r = await client.post(
        "/users/me/agents", json={"name": "dup"}, headers=two_users["alice"]
    )
    assert r.status_code == 409
