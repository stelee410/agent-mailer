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
