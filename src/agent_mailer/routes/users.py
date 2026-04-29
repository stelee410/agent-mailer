import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from agent_mailer.auth import (
    create_session_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from agent_mailer.db import db_transaction, get_invite_required
from agent_mailer.dependencies import get_current_user
from agent_mailer.models import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ChangePasswordRequest,
    LoginResponse,
    RegistrationConfigResponse,
    UpdateFilterTagsRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

USERNAME_RE = re.compile(r"^[a-z0-9-]{3,30}$")


@router.get("/registration-config", response_model=RegistrationConfigResponse)
async def registration_config(request: Request):
    """Public endpoint — lets the registration page detect whether to ask for an invite code."""
    db = request.app.state.db
    return RegistrationConfigResponse(invite_required=await get_invite_required(db))


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(request: Request, body: UserRegisterRequest):
    if not USERNAME_RE.match(body.username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-30 characters, lowercase letters, digits, or hyphens",
        )
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    db = request.app.state.db
    invite_required = await get_invite_required(db)
    if invite_required and not (body.invite_code and body.invite_code.strip()):
        raise HTTPException(status_code=400, detail="Invite code is required")

    cursor = await db.execute("SELECT id FROM users WHERE username = ?", (body.username,))
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail="Username already taken")

    # Check if this is the first user → superadmin
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    is_first_user = row["cnt"] == 0

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        async with db_transaction(db):
            await db.execute(
                "INSERT INTO users (id, username, password_hash, is_superadmin, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, body.username, hash_password(body.password), int(is_first_user), now),
            )
            if invite_required:
                cursor = await db.execute(
                    "UPDATE invite_codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
                    (user_id, now, body.invite_code),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=400, detail="Invalid or already used invite code")
    except HTTPException:
        raise
    return UserResponse(
        id=user_id,
        username=body.username,
        is_superadmin=is_first_user,
        created_at=now,
    )


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, response: Response, body: UserLoginRequest):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM users WHERE username = ?", (body.username,))
    user = await cursor.fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session_token(user["id"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=24 * 3600,
    )
    return LoginResponse(
        token=token,
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            is_superadmin=bool(user["is_superadmin"]),
            created_at=user["created_at"],
            filter_tags=_parse_filter_tags(dict(user)),
        ),
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="session_token", path="/")
    return {"detail": "Logged out"}


def _parse_filter_tags(user: dict) -> list[str]:
    raw = user.get("filter_tags", "[]")
    if isinstance(raw, str):
        import json
        return json.loads(raw)
    return raw or []


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(
        id=user["id"],
        username=user["username"],
        is_superadmin=bool(user["is_superadmin"]),
        created_at=user["created_at"],
        filter_tags=_parse_filter_tags(user),
    )


@router.put("/me/filter-tags", response_model=UserResponse)
async def update_filter_tags(
    request: Request, body: UpdateFilterTagsRequest, user: dict = Depends(get_current_user)
):
    import json
    db = request.app.state.db
    await db.execute(
        "UPDATE users SET filter_tags = ? WHERE id = ?",
        (json.dumps(body.filter_tags, ensure_ascii=False), user["id"]),
    )
    await db.commit()
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user["id"],))
    updated = await cursor.fetchone()
    return UserResponse(
        id=updated["id"],
        username=updated["username"],
        is_superadmin=bool(updated["is_superadmin"]),
        created_at=updated["created_at"],
        filter_tags=_parse_filter_tags(dict(updated)),
    )


@router.put("/me/password")
async def change_password(
    request: Request, body: ChangePasswordRequest, user: dict = Depends(get_current_user)
):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    db = request.app.state.db
    await db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(body.new_password), user["id"]),
    )
    await db.commit()
    return {"detail": "Password changed successfully"}


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    request: Request, body: ApiKeyCreateRequest, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    raw_key, key_hash = generate_api_key()
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO api_keys (id, user_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, user["id"], key_hash, body.name, now),
    )
    await db.commit()
    prefix = raw_key[:8] + "..." + raw_key[-4:]
    return ApiKeyCreateResponse(
        id=key_id,
        name=body.name,
        key_prefix=prefix,
        created_at=now,
        last_used_at=None,
        is_active=True,
        raw_key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        # Reconstruct prefix from hash — we don't store the raw key,
        # so show a generic masked prefix
        results.append(
            ApiKeyResponse(
                id=row["id"],
                name=row["name"],
                key_prefix="amk_****...****",
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
                is_active=bool(row["is_active"]),
            )
        )
    return results


@router.post("/api-keys/{key_id}/deactivate")
async def deactivate_api_key(
    request: Request, key_id: str, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user["id"])
    )
    if await cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    await db.commit()
    return {"detail": "API key deactivated"}


@router.post("/api-keys/{key_id}/reactivate")
async def reactivate_api_key(
    request: Request, key_id: str, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user["id"])
    )
    if await cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
    await db.commit()
    return {"detail": "API key reactivated"}


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    request: Request, key_id: str, user: dict = Depends(get_current_user)
):
    """Revoke (soft-delete) an API key. Row is kept for audit; subsequent calls return 401."""
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user["id"])
    )
    if await cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
