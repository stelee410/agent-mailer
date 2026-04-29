from typing import Literal

import markdown as _md
from pydantic import BaseModel, Field

ForwardScope = Literal["message", "thread"]

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
    tags: list[str] = []
    created_at: str
    last_seen: str | None = None
    status: str = "offline"
    team_id: str | None = None


class AgentUpdateAddressRequest(BaseModel):
    address: str


class AgentUpdateTagsRequest(BaseModel):
    tags: list[str]


class AgentSetupResponse(BaseModel):
    agent_md: str
    claude_md: str
    infiniti_md: str
    instructions: str


class SendRequest(BaseModel):
    agent_id: str  # sender's agent ID, must match from_agent address
    from_agent: str  # sender address
    to_agent: str | list[str]  # recipient address(es), supports single or multiple
    action: str = "send"
    subject: str = ""
    body: str = ""
    attachments: list[str | dict] = []
    parent_id: str | None = None
    # When action is forward: build body from parent / thread plus optional note in body.
    forward_scope: ForwardScope | None = None


class MessageResponse(BaseModel):
    id: str
    thread_id: str
    from_agent: str  # address
    to_agent: str  # address
    action: str
    subject: str
    body: str
    body_html: str  # markdown-rendered HTML
    attachments: list[str | dict]
    is_read: bool
    parent_id: str | None
    created_at: str


class AdminSendRequest(BaseModel):
    to_agent: str | list[str]  # recipient address(es), supports single or multiple
    action: str = "send"
    subject: str = ""
    body: str = ""
    parent_id: str | None = None
    forward_scope: ForwardScope | None = None


class AgentStats(BaseModel):
    agent_id: str
    name: str
    address: str
    role: str
    tags: list[str] = []
    messages_received: int = 0
    messages_read: int = 0
    messages_unread: int = 0
    messages_sent: int = 0
    messages_replied: int = 0
    messages_forwarded: int = 0
    last_seen: str | None = None
    status: str = "offline"


class ThreadSummary(BaseModel):
    thread_id: str
    last_activity: str
    message_count: int
    unread_count: int
    preview_subject: str = ""
    archived_at: str | None = None  # set when listing archived threads
    trashed_at: str | None = None  # set when listing trash


class ThreadArchiveStatus(BaseModel):
    archived: bool
    archived_at: str | None = None


class ThreadOperatorStatus(BaseModel):
    """Archive + trash flags for operator console thread actions."""

    archived: bool
    trashed: bool
    archived_at: str | None = None
    trashed_at: str | None = None


class TrashedMessageListItem(BaseModel):
    message_id: str
    thread_id: str
    trashed_at: str
    from_agent: str
    to_agent: str
    action: str
    subject: str
    created_at: str


class TrashedMessageDetail(BaseModel):
    trashed_at: str
    message: MessageResponse


# --- User / Auth models ---


class UserRegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str | None = None


class RegistrationConfigResponse(BaseModel):
    invite_required: bool


class SystemSettingsResponse(BaseModel):
    invite_required: bool


class SystemSettingsUpdateRequest(BaseModel):
    invite_required: bool


# --- Superadmin: managed agents ---


class AdminAgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    address_local: str | None = None  # local-part of address; defaults to name
    role: str = ""
    description: str = ""
    system_prompt: str = ""
    tags: list[str] = []
    team_id: str | None = None


class AdminAgentUpdateRequest(BaseModel):
    role: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    tags: list[str] | None = None
    team_id: str | None = None


class AdminAgentResponse(BaseModel):
    id: str
    name: str
    address: str
    role: str
    description: str
    system_prompt: str
    tags: list[str] = []
    team_id: str | None = None
    status: str = "active"
    created_at: str
    last_seen: str | None = None
    api_key_masked: str = ""  # e.g. "amk_****abc123" for table display


class AdminAgentCreateResponse(AdminAgentResponse):
    api_key_plaintext: str  # one-time only


class AdminAgentRegenerateKeyResponse(BaseModel):
    agent_id: str
    api_key_masked: str
    api_key_plaintext: str


class AdminAgentExportResponse(BaseModel):
    filename: str
    content: str


class UserLoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    is_superadmin: bool
    created_at: str
    filter_tags: list[str] = []


class UpdateFilterTagsRequest(BaseModel):
    filter_tags: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ApiKeyCreateRequest(BaseModel):
    name: str = ""


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: str | None
    is_active: bool


class ApiKeyCreateResponse(ApiKeyResponse):
    raw_key: str


class InviteCodeResponse(BaseModel):
    code: str
    created_by: str
    used_by: str | None
    used_at: str | None
    created_at: str


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


# --- Team models ---


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""


class TeamUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str
    user_id: str
    created_at: str
    agent_count: int = 0


class TeamDetailResponse(TeamResponse):
    agents: list[AgentResponse] = []


class SearchResultItem(BaseModel):
    message_id: str
    thread_id: str
    subject: str
    body_snippet: str
    from_agent: str
    to_agent: str
    created_at: str


class SearchResponse(BaseModel):
    messages: list[SearchResultItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    query: str


class PaginatedInboxResponse(BaseModel):
    messages: list[MessageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TeamAddAgentRequest(BaseModel):
    agent_id: str


# --- Memory models ---


class MemoryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=200000)


class MemoryUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, max_length=200000)


class MemoryUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=200000)


class MemoryResponse(BaseModel):
    id: str
    team_id: str
    title: str
    content: str
    user_id: str
    created_at: str
    updated_at: str
    updated_by: str
