import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from agent_mailer.auth import generate_api_key
from agent_mailer.db import db_transaction
from agent_mailer.dependencies import get_current_user
from agent_mailer.models import (
    AgentResponse,
    TeamAddAgentRequest,
    TeamBootstrapAgentResult,
    TeamBootstrapRequest,
    TeamBootstrapResponse,
    TeamCreateRequest,
    TeamDetailResponse,
    TeamResponse,
    TeamUpdateRequest,
)
from agent_mailer.routes.agents import _parse_agent
from agent_mailer.routes.me_agents import (
    _ADDRESS_LOCAL_RE,
    _build_user_agent_md,
    _user_domain_suffix,
)
from agent_mailer.utils import get_base_url

router = APIRouter(prefix="/admin/teams")


@router.post("", response_model=TeamResponse)
async def create_team(req: TeamCreateRequest, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    team_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Check name uniqueness within user
    cursor = await db.execute(
        "SELECT id FROM teams WHERE name = ? AND user_id = ?", (req.name, user["id"])
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Team name '{req.name}' already exists")

    await db.execute(
        "INSERT INTO teams (id, name, description, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (team_id, req.name, req.description, user["id"], now),
    )
    await db.commit()
    return TeamResponse(
        id=team_id, name=req.name, description=req.description,
        user_id=user["id"], created_at=now, agent_count=0,
    )


@router.get("", response_model=list[TeamResponse])
async def list_teams(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute(
        """SELECT t.*, COUNT(a.id) AS agent_count
           FROM teams t
           LEFT JOIN agents a ON a.team_id = t.id
           WHERE t.user_id = ?
           GROUP BY t.id
           ORDER BY t.created_at""",
        (user["id"],),
    )
    rows = await cursor.fetchall()
    return [TeamResponse(**dict(r)) for r in rows]


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(team_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM teams WHERE id = ? AND user_id = ?", (team_id, user["id"])
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Team not found")

    cursor = await db.execute(
        "SELECT * FROM agents WHERE team_id = ? ORDER BY created_at", (team_id,)
    )
    agent_rows = await cursor.fetchall()
    agents = [AgentResponse(**_parse_agent(r)) for r in agent_rows]

    return TeamDetailResponse(**dict(row), agent_count=len(agents), agents=agents)


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str, req: TeamUpdateRequest, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT * FROM teams WHERE id = ? AND user_id = ?", (team_id, user["id"])
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Team not found")

    name = req.name if req.name is not None else row["name"]
    description = req.description if req.description is not None else row["description"]

    # Check name uniqueness if changed
    if req.name is not None and req.name != row["name"]:
        cursor = await db.execute(
            "SELECT id FROM teams WHERE name = ? AND user_id = ? AND id != ?",
            (req.name, user["id"], team_id),
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail=f"Team name '{req.name}' already exists")

    await db.execute(
        "UPDATE teams SET name = ?, description = ? WHERE id = ?",
        (name, description, team_id),
    )
    await db.commit()

    # Get agent count
    cursor = await db.execute("SELECT COUNT(*) AS cnt FROM agents WHERE team_id = ?", (team_id,))
    cnt_row = await cursor.fetchone()

    return TeamResponse(
        id=team_id, name=name, description=description,
        user_id=user["id"], created_at=row["created_at"],
        agent_count=cnt_row["cnt"] if cnt_row else 0,
    )


@router.delete("/{team_id}")
async def delete_team(team_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    cursor = await db.execute(
        "SELECT id FROM teams WHERE id = ? AND user_id = ?", (team_id, user["id"])
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Team not found")

    # Clear team_id on agents
    await db.execute("UPDATE agents SET team_id = NULL WHERE team_id = ?", (team_id,))
    await db.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    await db.commit()
    return {"detail": "Team deleted", "team_id": team_id}


@router.post("/{team_id}/agents")
async def add_agent_to_team(
    team_id: str, req: TeamAddAgentRequest, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db

    # Verify team belongs to user
    cursor = await db.execute(
        "SELECT id FROM teams WHERE id = ? AND user_id = ?", (team_id, user["id"])
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify agent belongs to user
    cursor = await db.execute(
        "SELECT id, team_id FROM agents WHERE id = ? AND user_id = ?", (req.agent_id, user["id"])
    )
    agent = await cursor.fetchone()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent["team_id"] and agent["team_id"] != team_id:
        raise HTTPException(
            status_code=409,
            detail="Agent already belongs to another team. Remove it from that team first.",
        )

    await db.execute("UPDATE agents SET team_id = ? WHERE id = ?", (team_id, req.agent_id))
    await db.commit()
    return {"detail": "Agent added to team", "team_id": team_id, "agent_id": req.agent_id}


@router.delete("/{team_id}/agents/{agent_id}")
async def remove_agent_from_team(
    team_id: str, agent_id: str, request: Request, user: dict = Depends(get_current_user)
):
    db = request.app.state.db

    # Verify team belongs to user
    cursor = await db.execute(
        "SELECT id FROM teams WHERE id = ? AND user_id = ?", (team_id, user["id"])
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Team not found")

    # Verify agent is in this team
    cursor = await db.execute(
        "SELECT id FROM agents WHERE id = ? AND team_id = ? AND user_id = ?",
        (agent_id, team_id, user["id"]),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Agent not found in this team")

    await db.execute("UPDATE agents SET team_id = NULL WHERE id = ?", (agent_id,))
    await db.commit()
    return {"detail": "Agent removed from team", "team_id": team_id, "agent_id": agent_id}


@router.post("/bootstrap", response_model=TeamBootstrapResponse)
async def bootstrap_team(
    req: TeamBootstrapRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """One-shot create: a team plus N agents in a single transaction.

    Designed for the ``agent-mailer up-team`` CLI. Returns each agent's
    one-time API key plus a rendered AGENT.md. AGENT.md uses
    ``${AMP_API_KEY}`` instead of the inline placeholder so the file is
    safe to drop next to a per-agent ``.env``.
    """
    db = request.app.state.db
    suffix = _user_domain_suffix(user["username"])

    cursor = await db.execute(
        "SELECT id FROM teams WHERE name = ? AND user_id = ?", (req.name, user["id"])
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Team name '{req.name}' already exists")

    seen_locals: dict[str, str] = {}
    normalized: list[dict] = []
    for spec in req.agents:
        local = (spec.address_local or spec.name).strip().lower()
        if not _ADDRESS_LOCAL_RE.match(local):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Agent '{spec.name}': address local part must be lowercase "
                    "letters/digits/._- with alphanumeric on both ends"
                ),
            )
        if local in seen_locals:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Duplicate address local '{local}' within request "
                    f"(agents '{seen_locals[local]}' and '{spec.name}')"
                ),
            )
        seen_locals[local] = spec.name
        normalized.append({"spec": spec, "local": local, "address": f"{local}{suffix}"})

    addresses = [n["address"] for n in normalized]
    placeholders = ",".join("?" * len(addresses))
    cursor = await db.execute(
        f"SELECT address FROM agents WHERE address IN ({placeholders})", tuple(addresses)
    )
    taken = [row["address"] for row in await cursor.fetchall()]
    if taken:
        raise HTTPException(
            status_code=409, detail=f"Address(es) already taken: {', '.join(taken)}"
        )

    team_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    created: list[dict] = []

    async with db_transaction(db):
        await db.execute(
            "INSERT INTO teams (id, name, description, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (team_id, req.name, req.description, user["id"], now),
        )
        for n in normalized:
            spec = n["spec"]
            agent_id = str(uuid.uuid4())
            raw_key, key_hash = generate_api_key()
            key_suffix = raw_key[-6:]

            await db.execute(
                """INSERT INTO agents (id, name, address, role, description, system_prompt,
                       tags, user_id, created_at, status, api_key_suffix, team_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    agent_id,
                    spec.name,
                    n["address"],
                    spec.role or "",
                    spec.description or "",
                    spec.system_prompt or "",
                    json.dumps(spec.tags, ensure_ascii=False),
                    user["id"],
                    now,
                    key_suffix,
                    team_id,
                ),
            )
            await db.execute(
                "INSERT INTO api_keys (id, user_id, key_hash, name, created_at, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (str(uuid.uuid4()), user["id"], key_hash, f"agent:{agent_id}", now),
            )
            created.append(
                {
                    "id": agent_id,
                    "name": spec.name,
                    "role": spec.role or "",
                    "address": n["address"],
                    "system_prompt": spec.system_prompt or "",
                    "raw_key": raw_key,
                }
            )

    broker_url = get_base_url(request)
    results: list[TeamBootstrapAgentResult] = []
    for c in created:
        md = _build_user_agent_md(
            {
                "id": c["id"],
                "name": c["name"],
                "role": c["role"],
                "address": c["address"],
                "system_prompt": c["system_prompt"],
            },
            broker_url,
            suffix,
        ).replace("<your_api_key>", "${AMP_API_KEY}")
        results.append(
            TeamBootstrapAgentResult(
                agent_id=c["id"],
                name=c["name"],
                address=c["address"],
                role=c["role"],
                api_key_plaintext=c["raw_key"],
                agent_md=md,
            )
        )

    team_response = TeamResponse(
        id=team_id,
        name=req.name,
        description=req.description,
        user_id=user["id"],
        created_at=now,
        agent_count=len(created),
    )
    return TeamBootstrapResponse(team=team_response, agents=results)
