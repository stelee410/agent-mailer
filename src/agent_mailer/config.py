import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (walk up from this file: config.py -> agent_mailer -> src -> project root)
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env")

DOMAIN: str = os.environ.get("AGENT_MAILER_DOMAIN", "amp.linkyun.co")
UPLOAD_DIR: str = os.environ.get("AGENT_MAILER_UPLOAD_DIR", "uploads")

_secret_key: str | None = None


def get_secret_key() -> str:
    global _secret_key
    if _secret_key is None:
        value = os.environ.get("AGENT_MAILER_SECRET_KEY")
        if not value:
            raise RuntimeError(
                "Environment variable AGENT_MAILER_SECRET_KEY is required but not set"
            )
        _secret_key = value
    return _secret_key
