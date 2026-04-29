import os

os.environ.setdefault(
    "AGENT_MAILER_SECRET_KEY",
    "test-secret-key-that-is-at-least-32-bytes-long",
)

import pytest
from httpx import ASGITransport, AsyncClient

from agent_mailer.auth import verify_session_token
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
async def bootstrap_code(client):
    """Return bootstrap invite code for the empty DB."""
    db = client._transport.app.state.db  # noqa
    code = await ensure_bootstrap_invite_code(db)
    return code


@pytest.fixture
async def superadmin(client, bootstrap_code):
    """Register and login as superadmin, return (client, token, user)."""
    resp = await client.post(
        "/users/register",
        json={
            "username": "admin",
            "password": "admin-password-123",
            "invite_code": bootstrap_code,
        },
    )
    assert resp.status_code == 201
    user = resp.json()
    assert user["is_superadmin"] is True

    resp = await client.post(
        "/users/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    return client, token, user


# --- Bootstrap ---


async def test_bootstrap_invite_code_generated(client):
    db = client._transport.app.state.db  # noqa
    code = await ensure_bootstrap_invite_code(db)
    assert code is not None
    assert len(code) == 8


async def test_bootstrap_idempotent(client):
    db = client._transport.app.state.db  # noqa
    code1 = await ensure_bootstrap_invite_code(db)
    code2 = await ensure_bootstrap_invite_code(db)
    assert code1 == code2


async def test_bootstrap_not_generated_when_users_exist(client, superadmin):
    db = client._transport.app.state.db  # noqa
    code = await ensure_bootstrap_invite_code(db)
    assert code is None


# --- Registration ---


async def test_register_first_user_is_superadmin(client, bootstrap_code):
    resp = await client.post(
        "/users/register",
        json={
            "username": "first-user",
            "password": "password123",
            "invite_code": bootstrap_code,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["is_superadmin"] is True
    assert data["username"] == "first-user"


async def test_register_invalid_invite_code(client):
    resp = await client.post(
        "/users/register",
        json={
            "username": "testuser",
            "password": "password123",
            "invite_code": "INVALID0",
        },
    )
    assert resp.status_code == 400
    assert "invite code" in resp.json()["detail"].lower()


async def test_register_used_invite_code(client, superadmin):
    c, token, _ = superadmin
    # Create an invite code
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    code = resp.json()["code"]
    # Use it
    await c.post(
        "/users/register",
        json={"username": "user-one", "password": "password123", "invite_code": code},
    )
    # Try to reuse
    resp = await c.post(
        "/users/register",
        json={"username": "user-two", "password": "password123", "invite_code": code},
    )
    assert resp.status_code == 400


async def test_register_duplicate_username(client, superadmin):
    c, token, _ = superadmin
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    code1 = resp.json()["code"]
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    code2 = resp.json()["code"]

    await c.post(
        "/users/register",
        json={"username": "dupuser", "password": "password123", "invite_code": code1},
    )
    resp = await c.post(
        "/users/register",
        json={"username": "dupuser", "password": "password123", "invite_code": code2},
    )
    assert resp.status_code == 409


async def test_register_invalid_username_format(client, bootstrap_code):
    resp = await client.post(
        "/users/register",
        json={"username": "AB", "password": "password123", "invite_code": bootstrap_code},
    )
    assert resp.status_code == 400
    assert "username" in resp.json()["detail"].lower()


async def test_register_password_too_short(client, bootstrap_code):
    resp = await client.post(
        "/users/register",
        json={"username": "validuser", "password": "short", "invite_code": bootstrap_code},
    )
    assert resp.status_code == 400
    assert "password" in resp.json()["detail"].lower()


# --- Login ---


async def test_login_success(client, bootstrap_code):
    await client.post(
        "/users/register",
        json={
            "username": "loginuser",
            "password": "password123",
            "invite_code": bootstrap_code,
        },
    )
    resp = await client.post(
        "/users/login",
        json={"username": "loginuser", "password": "password123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["username"] == "loginuser"
    assert "session_token" in resp.cookies


async def test_login_wrong_password(client, bootstrap_code):
    await client.post(
        "/users/register",
        json={
            "username": "loginuser2",
            "password": "password123",
            "invite_code": bootstrap_code,
        },
    )
    resp = await client.post(
        "/users/login",
        json={"username": "loginuser2", "password": "wrongpass"},
    )
    assert resp.status_code == 401


async def test_login_nonexistent_user(client):
    resp = await client.post(
        "/users/login",
        json={"username": "nouser", "password": "password123"},
    )
    assert resp.status_code == 401


# --- /users/me ---


async def test_me_authenticated(client, superadmin):
    c, token, user = superadmin
    resp = await c.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


async def test_me_unauthenticated(client):
    resp = await client.get("/users/me")
    assert resp.status_code == 401


# --- API Keys ---


async def test_api_key_lifecycle(client, superadmin):
    c, token, _ = superadmin

    # Create
    resp = await c.post(
        "/users/api-keys",
        json={"name": "test-key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["raw_key"].startswith("amk_")
    assert data["name"] == "test-key"
    assert data["is_active"] is True
    key_id = data["id"]
    raw_key = data["raw_key"]

    # List
    resp = await c.get(
        "/users/api-keys", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 1
    assert keys[0]["id"] == key_id
    assert "raw_key" not in keys[0]  # raw key not in list response

    # Use API key to access /users/me
    resp = await c.get("/users/me", headers={"X-API-Key": raw_key})
    # Note: /users/me uses get_current_user (JWT), not get_api_key_user
    # This should return 401 since X-API-Key is not a JWT bearer token
    # API key auth is a separate dependency

    # Deactivate
    resp = await c.delete(
        f"/users/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    # Verify deactivated
    resp = await c.get(
        "/users/api-keys", headers={"Authorization": f"Bearer {token}"}
    )
    keys = resp.json()
    assert keys[0]["is_active"] is False


async def test_api_key_not_found(client, superadmin):
    c, token, _ = superadmin
    resp = await c.delete(
        "/users/api-keys/nonexistent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# --- Superadmin endpoints ---


async def test_superadmin_create_invite_code(client, superadmin):
    c, token, _ = superadmin
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["code"]) == 8
    assert data["used_by"] is None


async def test_superadmin_list_invite_codes(client, superadmin):
    c, token, _ = superadmin
    await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await c.get(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    codes = resp.json()
    assert len(codes) >= 1


async def test_superadmin_list_users(client, superadmin):
    c, token, _ = superadmin
    resp = await c.get(
        "/superadmin/users", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"


async def test_superadmin_login_as(client, superadmin):
    c, token, admin_user = superadmin
    # Create a regular user
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    code = resp.json()["code"]
    resp = await c.post(
        "/users/register",
        json={"username": "regular", "password": "password123", "invite_code": code},
    )
    target_id = resp.json()["id"]

    # Login as
    resp = await c.post(
        f"/superadmin/login-as/{target_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == "regular"
    payload = verify_session_token(data["token"])
    assert payload["user_id"] == target_id
    assert payload["impersonated_by"] == admin_user["id"]


async def test_superadmin_login_as_not_found(client, superadmin):
    c, token, _ = superadmin
    resp = await c.post(
        "/superadmin/login-as/nonexistent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_non_superadmin_forbidden(client, superadmin):
    c, token, _ = superadmin
    # Create regular user
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    code = resp.json()["code"]
    await c.post(
        "/users/register",
        json={"username": "regular2", "password": "password123", "invite_code": code},
    )
    resp = await c.post(
        "/users/login",
        json={"username": "regular2", "password": "password123"},
    )
    regular_token = resp.json()["token"]

    # Try superadmin endpoints
    resp = await c.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403

    resp = await c.get(
        "/superadmin/users",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403


# --- Registration toggle (invite_required setting) ---


async def test_registration_config_default(client):
    resp = await client.get("/users/registration-config")
    assert resp.status_code == 200
    assert resp.json() == {"invite_required": True}


async def test_admin_settings_get_default(client, superadmin):
    c, token, _ = superadmin
    resp = await c.get(
        "/superadmin/settings", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"invite_required": True}


async def test_admin_settings_non_superadmin_forbidden(client, superadmin):
    c, token, _ = superadmin
    resp = await c.post(
        "/superadmin/invite-codes", headers={"Authorization": f"Bearer {token}"}
    )
    code = resp.json()["code"]
    await c.post(
        "/users/register",
        json={"username": "regtoggle", "password": "password123", "invite_code": code},
    )
    resp = await c.post(
        "/users/login",
        json={"username": "regtoggle", "password": "password123"},
    )
    regular_token = resp.json()["token"]

    resp = await c.get(
        "/superadmin/settings",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403

    resp = await c.put(
        "/superadmin/settings",
        json={"invite_required": False},
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403


async def test_registration_open_when_invite_disabled(client, superadmin):
    c, token, _ = superadmin

    resp = await c.put(
        "/superadmin/settings",
        json={"invite_required": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"invite_required": False}

    resp = await c.get("/users/registration-config")
    assert resp.json() == {"invite_required": False}

    # Without invite_code: succeeds.
    resp = await c.post(
        "/users/register",
        json={"username": "openuser", "password": "password123"},
    )
    assert resp.status_code == 201

    # Even an invalid invite_code is ignored when the setting is off.
    resp = await c.post(
        "/users/register",
        json={"username": "openuser2", "password": "password123", "invite_code": "INVALID0"},
    )
    assert resp.status_code == 201


async def test_registration_still_requires_invite_when_enabled(client, superadmin):
    c, token, _ = superadmin

    # Disable, then re-enable.
    await c.put(
        "/superadmin/settings",
        json={"invite_required": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await c.put(
        "/superadmin/settings",
        json={"invite_required": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json() == {"invite_required": True}

    # Missing invite_code → 400.
    resp = await c.post(
        "/users/register",
        json={"username": "needsinvite", "password": "password123"},
    )
    assert resp.status_code == 400

    # Invalid invite_code → 400.
    resp = await c.post(
        "/users/register",
        json={"username": "needsinvite2", "password": "password123", "invite_code": "BAD12345"},
    )
    assert resp.status_code == 400


# --- Superadmin: managed agents (Agents Management) ---


async def test_admin_agents_create_lists_and_masks_key(client, superadmin):
    c, token, _ = superadmin
    r = await c.post(
        "/superadmin/agents",
        json={"name": "pm", "role": "pm", "system_prompt": "Hi."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["address"] == "pm@admin.amp.linkyun.co"
    assert body["status"] == "active"
    assert body["api_key_plaintext"].startswith("amk_")
    assert body["api_key_masked"].startswith("amk_****") and len(body["api_key_masked"]) == 14
    aid = body["id"]

    r = await c.get("/superadmin/agents", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert any(a["id"] == aid for a in r.json())
    # plaintext never appears in list responses
    assert all("api_key_plaintext" not in a for a in r.json())


async def test_admin_agents_duplicate_address_409(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    await c.post("/superadmin/agents", json={"name": "dup"}, headers=h)
    r = await c.post("/superadmin/agents", json={"name": "dup"}, headers=h)
    assert r.status_code == 409


async def test_admin_agents_invalid_address_local(client, superadmin):
    c, token, _ = superadmin
    r = await c.post(
        "/superadmin/agents",
        json={"name": "bad", "address_local": "Has Space"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


async def test_admin_agents_update_only_allowed_fields(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post("/superadmin/agents", json={"name": "edit"}, headers=h)
    aid = r.json()["id"]
    addr = r.json()["address"]
    r = await c.put(
        f"/superadmin/agents/{aid}",
        json={"role": "coder", "description": "updated", "tags": ["p1"]},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "coder"
    assert r.json()["description"] == "updated"
    assert r.json()["tags"] == ["p1"]
    # name/address unchanged
    assert r.json()["address"] == addr


async def test_admin_agents_soft_delete_and_address_reserved(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post("/superadmin/agents", json={"name": "softdel"}, headers=h)
    aid = r.json()["id"]
    r = await c.delete(f"/superadmin/agents/{aid}", headers=h)
    assert r.status_code == 200

    r = await c.get("/superadmin/agents", headers=h)
    assert all(a["id"] != aid for a in r.json())

    r = await c.get("/superadmin/agents?include_deleted=true", headers=h)
    assert any(a["id"] == aid and a["status"] == "deleted" for a in r.json())

    # Address is reserved.
    r = await c.post("/superadmin/agents", json={"name": "softdel"}, headers=h)
    assert r.status_code == 409


async def test_admin_agents_regenerate_key_invalidates_old(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post("/superadmin/agents", json={"name": "rotate"}, headers=h)
    aid = r.json()["id"]
    old_key = r.json()["api_key_plaintext"]

    # Old key works.
    r = await c.get("/agents", headers={"X-API-Key": old_key})
    assert r.status_code == 200

    r = await c.post(f"/superadmin/agents/{aid}/regenerate-key", headers=h)
    assert r.status_code == 200
    new_key = r.json()["api_key_plaintext"]
    assert new_key != old_key

    r_old = await c.get("/agents", headers={"X-API-Key": old_key})
    assert r_old.status_code == 401
    r_new = await c.get("/agents", headers={"X-API-Key": new_key})
    assert r_new.status_code == 200


async def test_admin_agents_export_agent_md_and_soul_md(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post(
        "/superadmin/agents",
        json={"name": "exp", "system_prompt": "exp prompt"},
        headers=h,
    )
    aid = r.json()["id"]
    r = await c.get(
        f"/superadmin/agents/{aid}/export?format=agent_md", headers=h
    )
    assert r.status_code == 200
    a_body = r.json()
    assert a_body["filename"] == "AGENT.md"
    assert "exp prompt" in a_body["content"]
    assert "<your_api_key>" in a_body["content"]
    # P3-1: bilingual security note must appear, between Identity and System Prompt sections.
    assert "Security Note" in a_body["content"] and "安全须知" in a_body["content"]
    sec_idx = a_body["content"].index("Security Note")
    sys_idx = a_body["content"].index("身份提示词")
    assert sec_idx < sys_idx

    r = await c.get(
        f"/superadmin/agents/{aid}/export?format=soul_md", headers=h
    )
    s_body = r.json()
    assert s_body["filename"] == "SOUL.md"
    assert s_body["content"] == a_body["content"]


def test_views_js_regen_closes_export_modal_before_confirm():
    """Regression for the production P2: clicking 'Regenerate Key &
    Download' from inside the Export Modal must close the modal *before*
    showing the confirm dialog. The Export Modal and ``showConfirm``
    share the same ``.modal-overlay`` z-index, so leaving them stacked
    hides the confirm behind the export view (user reported they
    couldn't see the confirm at all).
    """
    import pathlib
    src = pathlib.Path(
        __file__
    ).resolve().parent.parent / "src" / "agent_mailer" / "static" / "js" / "views.js"
    text = src.read_text(encoding="utf-8")
    fn_marker = "async function regenAndDownloadAdminAgentMd("
    fn_start = text.index(fn_marker)
    # Bound the search to the function's body — find the next top-level
    # ``async function``/``function`` definition or end-of-file.
    fn_end_candidates = [text.find(token, fn_start + len(fn_marker))
                         for token in ("\nasync function ", "\nfunction ")]
    fn_end_candidates = [pos for pos in fn_end_candidates if pos > 0]
    fn_end = min(fn_end_candidates) if fn_end_candidates else len(text)
    body = text[fn_start:fn_end]
    close_idx = body.find("closeAdminAgentModal()")
    confirm_idx = body.find("showConfirm(")
    assert close_idx >= 0, "regenAndDownloadAdminAgentMd must call closeAdminAgentModal()"
    assert confirm_idx >= 0, "regenAndDownloadAdminAgentMd must call showConfirm()"
    assert close_idx < confirm_idx, (
        "closeAdminAgentModal() must be called *before* showConfirm() in "
        "regenAndDownloadAdminAgentMd to prevent the modals from stacking."
    )


def test_views_js_export_modal_has_no_unsafe_inline_handlers():
    """Regression for the P2 finding: the export-modal Copy and
    Download(placeholder) buttons must not interpolate the AGENT.md
    payload into a double-quoted ``onclick`` attribute. The markdown
    contains both ``"`` (in the JSON request-body example) and ``'``
    (in the bilingual security note's "agent's mailbox"), so any inline
    handler that pours the content through ``JSON.stringify`` would
    silently break out of the HTML attribute.

    Enforced by reading the static asset and asserting the broken
    pattern is absent — the live wiring goes through ``addEventListener``.
    """
    import pathlib
    src = pathlib.Path(
        __file__
    ).resolve().parent.parent / "src" / "agent_mailer" / "static" / "js" / "views.js"
    text = src.read_text(encoding="utf-8")
    forbidden = [
        'onclick="copyText(${JSON.stringify(content)',
        'onclick="downloadTextAs(${JSON.stringify(',
    ]
    for pattern in forbidden:
        assert pattern not in text, (
            f"Re-introduced unsafe inline onclick handler: {pattern}. "
            "Use addEventListener after _adminAgentsModal() instead."
        )


async def test_admin_agents_regenerate_then_export_substitutes_plaintext(client, superadmin):
    """Documents the frontend orchestration sequence for the
    "Regenerate Key & Download" export action: regenerate-key returns
    a fresh plaintext, the export endpoint emits the placeholder
    template, and naive client-side substitution yields a file that
    contains the new plaintext API key (and not the placeholder).
    """
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post(
        "/superadmin/agents",
        json={"name": "regdl", "system_prompt": "the prompt"},
        headers=h,
    )
    aid = r.json()["id"]
    old_key = r.json()["api_key_plaintext"]

    r = await c.post(f"/superadmin/agents/{aid}/regenerate-key", headers=h)
    assert r.status_code == 200
    new_key = r.json()["api_key_plaintext"]
    assert new_key != old_key

    # Export still emits placeholder; the frontend is responsible for substitution.
    r = await c.get(f"/superadmin/agents/{aid}/export?format=agent_md", headers=h)
    assert r.status_code == 200
    raw_md = r.json()["content"]
    assert "<your_api_key>" in raw_md

    rendered = raw_md.replace("<your_api_key>", new_key)
    assert "<your_api_key>" not in rendered
    assert new_key in rendered
    # Identity + system prompt survived.
    assert "the prompt" in rendered

    # Old key really is revoked.
    r_old = await c.get("/agents", headers={"X-API-Key": old_key})
    assert r_old.status_code == 401


async def test_admin_agents_address_local_regex_tightened(client, superadmin):
    c, token, _ = superadmin
    h = {"Authorization": f"Bearer {token}"}
    # Trailing punctuation no longer accepted (P3-3).
    r = await c.post(
        "/superadmin/agents", json={"name": "x", "address_local": "foo."}, headers=h
    )
    assert r.status_code == 400
    r = await c.post(
        "/superadmin/agents", json={"name": "x", "address_local": "-foo"}, headers=h
    )
    assert r.status_code == 400
    # Single char and well-formed multi still work.
    r = await c.post("/superadmin/agents", json={"name": "x", "address_local": "a"}, headers=h)
    assert r.status_code == 201
    r = await c.post(
        "/superadmin/agents", json={"name": "y", "address_local": "a-b"}, headers=h
    )
    assert r.status_code == 201
    r = await c.post(
        "/superadmin/agents", json={"name": "z", "address_local": "foo.bar"}, headers=h
    )
    assert r.status_code == 201


async def test_admin_agents_non_superadmin_forbidden(client, superadmin):
    c, token, _ = superadmin
    r = await c.post(
        "/superadmin/invite-codes", headers={"Authorization": f"Bearer {token}"}
    )
    invite = r.json()["code"]
    await c.post(
        "/users/register",
        json={"username": "regularaa", "password": "pwd-norm-1234", "invite_code": invite},
    )
    r = await c.post(
        "/users/login", json={"username": "regularaa", "password": "pwd-norm-1234"}
    )
    nh = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await c.get("/superadmin/agents", headers=nh)).status_code == 403
    assert (await c.post("/superadmin/agents", json={"name": "x"}, headers=nh)).status_code == 403
    assert (
        await c.put("/superadmin/agents/missing", json={"role": "x"}, headers=nh)
    ).status_code == 403
    assert (await c.delete("/superadmin/agents/missing", headers=nh)).status_code == 403
    assert (
        await c.post("/superadmin/agents/missing/regenerate-key", headers=nh)
    ).status_code == 403
    assert (
        await c.get("/superadmin/agents/missing/export?format=agent_md", headers=nh)
    ).status_code == 403


# --- Full lifecycle E2E ---


async def test_full_user_lifecycle(client):
    db = client._transport.app.state.db  # noqa
    # 1. Bootstrap code
    code = await ensure_bootstrap_invite_code(db)
    assert code is not None

    # 2. Register superadmin
    resp = await client.post(
        "/users/register",
        json={
            "username": "superuser",
            "password": "super-pass-123",
            "invite_code": code,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["is_superadmin"] is True

    # 3. Login
    resp = await client.post(
        "/users/login",
        json={"username": "superuser", "password": "super-pass-123"},
    )
    assert resp.status_code == 200
    admin_token = resp.json()["token"]

    # 4. Generate invite code
    resp = await client.post(
        "/superadmin/invite-codes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    new_code = resp.json()["code"]

    # 5. Register regular user
    resp = await client.post(
        "/users/register",
        json={
            "username": "normaluser",
            "password": "normal-pass-123",
            "invite_code": new_code,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["is_superadmin"] is False

    # 6. Login as regular user
    resp = await client.post(
        "/users/login",
        json={"username": "normaluser", "password": "normal-pass-123"},
    )
    user_token = resp.json()["token"]

    # 7. Create API Key
    resp = await client.post(
        "/users/api-keys",
        json={"name": "my-key"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["raw_key"].startswith("amk_")
