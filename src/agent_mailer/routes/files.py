import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from agent_mailer.config import UPLOAD_DIR
from agent_mailer.dependencies import get_api_key_user, get_current_user

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _ensure_upload_dir(subdir: str) -> str:
    path = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile):
    # Auth: accept both session (WebUI) and API key (Agent)
    user = None
    try:
        user = await get_current_user(request)
    except HTTPException:
        try:
            user = await get_api_key_user(request)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Authentication required")

    # Validate MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Allowed: PNG, JPG, GIF, WebP",
        )

    # Read and validate size
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(data)} bytes. Maximum: {MAX_FILE_SIZE} bytes (10MB)",
        )

    # Generate ID and save
    file_id = str(uuid.uuid4())
    today = date.today().isoformat()
    dir_path = _ensure_upload_dir(today)

    # Preserve original extension
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    stored_name = file_id + ext
    file_path = os.path.join(dir_path, stored_name)

    with open(file_path, "wb") as f:
        f.write(data)

    # Store metadata in DB
    db = request.app.state.db
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO files (id, filename, mime_type, size, stored_path, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (file_id, file.filename or "untitled", content_type, len(data), file_path, user["id"], now),
    )
    await db.commit()

    from agent_mailer.utils import get_base_url
    base_url = get_base_url(request)
    url = f"{base_url}/files/{file_id}"

    return {
        "id": file_id,
        "filename": file.filename or "untitled",
        "mime_type": content_type,
        "size": len(data),
        "url": url,
    }


@router.get("/{file_id}")
async def get_file(file_id: str, request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    stored_path = row["stored_path"]
    if not os.path.exists(stored_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        stored_path,
        media_type=row["mime_type"],
        filename=row["filename"],
        headers={"Content-Disposition": "inline"},
    )
