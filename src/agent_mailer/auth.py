import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from agent_mailer.config import get_secret_key

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 365 * 100


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def generate_api_key() -> tuple[str, str]:
    raw_key = "amk_" + secrets.token_hex(32)
    key_hash = hash_api_key(raw_key)
    return raw_key, key_hash


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session_token(
    user_id: str, impersonated_by: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    if impersonated_by is not None:
        payload["impersonated_by"] = impersonated_by
    return jwt.encode(payload, get_secret_key(), algorithm=JWT_ALGORITHM)


def verify_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_secret_key(), algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
