import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from agent_mailer.auth import create_session_token
from agent_mailer.db import (
    SETTING_INVITE_REQUIRED,
    get_invite_required,
    set_setting,
)
from agent_mailer.dependencies import require_superadmin
from agent_mailer.models import (
    InviteCodeResponse,
    LoginResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    UserResponse,
)

router = APIRouter(prefix="/superadmin", tags=["superadmin"])

INVITE_CODE_CHARS = string.ascii_letters + string.digits
INVITE_CODE_LENGTH = 8


def _generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(INVITE_CODE_LENGTH))


@router.post("/invite-codes", response_model=InviteCodeResponse, status_code=201)
async def create_invite_code(
    request: Request, user: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    code = _generate_invite_code()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO invite_codes (code, created_by, created_at) VALUES (?, ?, ?)",
        (code, user["id"], now),
    )
    await db.commit()
    return InviteCodeResponse(
        code=code,
        created_by=user["id"],
        used_by=None,
        used_at=None,
        created_at=now,
    )


@router.get("/invite-codes", response_model=list[InviteCodeResponse])
async def list_invite_codes(
    request: Request, user: dict = Depends(require_superadmin)
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM invite_codes ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [
        InviteCodeResponse(
            code=row["code"],
            created_by=row["created_by"],
            used_by=row["used_by"],
            used_at=row["used_at"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/users", response_model=list[UserResponse])
async def list_users(request: Request, user: dict = Depends(require_superadmin)):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM users ORDER BY created_at")
    rows = await cursor.fetchall()
    return [
        UserResponse(
            id=row["id"],
            username=row["username"],
            is_superadmin=bool(row["is_superadmin"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/settings", response_model=SystemSettingsResponse)
async def get_system_settings(request: Request, user: dict = Depends(require_superadmin)):
    db = request.app.state.db
    return SystemSettingsResponse(invite_required=await get_invite_required(db))


@router.put("/settings", response_model=SystemSettingsResponse)
async def update_system_settings(
    request: Request,
    body: SystemSettingsUpdateRequest,
    user: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    await set_setting(db, SETTING_INVITE_REQUIRED, "1" if body.invite_required else "0")
    return SystemSettingsResponse(invite_required=await get_invite_required(db))


@router.post("/login-as/{user_id}", response_model=LoginResponse)
async def login_as(
    request: Request,
    response: Response,
    user_id: str,
    admin: dict = Depends(require_superadmin),
):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    target_user = await cursor.fetchone()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_session_token(user_id, impersonated_by=admin["id"])
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
            id=target_user["id"],
            username=target_user["username"],
            is_superadmin=bool(target_user["is_superadmin"]),
            created_at=target_user["created_at"],
        ),
    )
