import markdown as _md
from pydantic import BaseModel

_markdown_extensions = ["fenced_code", "tables", "nl2br", "sane_lists", "codehilite"]


def render_body_html(body: str) -> str:
    """Render markdown body to HTML."""
    return _md.markdown(body, extensions=_markdown_extensions)


class AgentRegisterRequest(BaseModel):
    name: str
    address: str | None = None  # defaults to {name}@local
    role: str
    description: str = ""
    system_prompt: str


class AgentResponse(BaseModel):
    id: str
    name: str
    address: str
    role: str
    description: str
    system_prompt: str
    created_at: str


class AgentUpdateAddressRequest(BaseModel):
    address: str


class AgentSetupResponse(BaseModel):
    agent_md: str
    claude_md: str
    instructions: str


class SendRequest(BaseModel):
    agent_id: str  # sender's agent ID, must match from_agent address
    from_agent: str  # sender address
    to_agent: str | list[str]  # recipient address(es), supports single or multiple
    action: str = "send"
    subject: str = ""
    body: str = ""
    attachments: list[str] = []
    parent_id: str | None = None


class MessageResponse(BaseModel):
    id: str
    thread_id: str
    from_agent: str  # address
    to_agent: str  # address
    action: str
    subject: str
    body: str
    body_html: str  # markdown-rendered HTML
    attachments: list[str]
    is_read: bool
    parent_id: str | None
    created_at: str


class AdminSendRequest(BaseModel):
    to_agent: str | list[str]  # recipient address(es), supports single or multiple
    action: str = "send"
    subject: str = ""
    body: str = ""
    parent_id: str | None = None


class AgentStats(BaseModel):
    agent_id: str
    name: str
    address: str
    role: str
    messages_received: int = 0
    messages_read: int = 0
    messages_unread: int = 0
    messages_sent: int = 0
    messages_replied: int = 0
    messages_forwarded: int = 0


class ThreadSummary(BaseModel):
    thread_id: str
    last_activity: str
    message_count: int
    unread_count: int
    preview_subject: str = ""
    archived_at: str | None = None  # set when listing archived threads


class ThreadArchiveStatus(BaseModel):
    archived: bool
    archived_at: str | None = None
