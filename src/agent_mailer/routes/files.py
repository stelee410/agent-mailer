import os
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from agent_mailer.config import UPLOAD_DIR
from agent_mailer.dependencies import get_api_key_user, get_current_user
from agent_mailer.utils import get_base_url

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Magic bytes signatures for image formats
_MAGIC_SIGS = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # RIFF....WEBP (check further below)
}


def _detect_mime(data: bytes) -> str | None:
    """Detect image MIME type from file header magic bytes."""
    for sig, mime in _MAGIC_SIGS.items():
        if data[:len(sig)] == sig:
            if mime == "image/webp":
                # RIFF header: bytes 8-12 should be "WEBP"
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return "image/webp"
                return None
            return mime
    return None


def _safe_extension(filename: str | None) -> str:
    """Extract and validate file extension against whitelist."""
    if not filename or "." not in filename:
        return ""
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else ""


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

    # Read and validate size
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {len(data)} bytes. Maximum: {MAX_FILE_SIZE} bytes (10MB)",
        )

    # Validate MIME type via magic bytes (P1-1)
    detected_mime = _detect_mime(data)
    if detected_mime is None or detected_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: PNG, JPG, GIF, WebP",
        )

    # Validate extension whitelist (P1-2)
    ext = _safe_extension(file.filename)
    if not ext:
        # Assign extension from detected MIME
        ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
        ext = ext_map.get(detected_mime, "")

    # Generate ID and save
    file_id = str(uuid.uuid4())
    today = date.today().isoformat()
    dir_path = _ensure_upload_dir(today)
    stored_name = file_id + ext
    file_path = os.path.join(dir_path, stored_name)

    with open(file_path, "wb") as f:
        f.write(data)

    # Store metadata in DB
    db = request.app.state.db
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO files (id, filename, mime_type, size, stored_path, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (file_id, file.filename or "untitled", detected_mime, len(data), file_path, user["id"], now),
    )
    await db.commit()

    base_url = get_base_url(request)
    url = f"{base_url}/files/{file_id}"

    return {
        "id": file_id,
        "filename": file.filename or "untitled",
        "mime_type": detected_mime,
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
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )
