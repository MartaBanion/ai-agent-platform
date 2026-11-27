from time import perf_counter
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import Field, SecretStr
from sqlalchemy import select

from app.ai_access import shared_agent
from app.ai_models import Agent
from app.knowledge_models import AgentTool, ToolCall, ToolServer
from app.mcp_runtime import OPS_URL, config, discover, execute, fingerprint, validate
from app.models import User
from app.provider import UpstreamError, canonical_url, encrypt_key
from app.schemas import Input, Name
from app.security import Admin, Db, Identity, audit

router = APIRouter(prefix="/mcp", tags=["MCP 工具中心"])


class ServerForm(Input):
    name: Name
    kind: Literal["builtin", "external"]
    url: str = Field("", max_length=320)
    api_key: SecretStr | None = Field(None, max_length=1024)
    clear_key: bool = False
    shared: bool = False
    enabled: bool = True
    approval: bool = True
    allowed: list[str] = Field(default_factory=list, max_length=50)


class RequestCall(Input):
    tool: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    arguments: dict = Field(default_factory=dict)
    agent_id: UUID | None = None


class Review(Input):
    approve: bool


def can_use(server, user):
    return server is not None and (user.role == "admin" or server.owner_id == user.id or
                                   (server.enabled and server.shared))


def state_data(row):
    return {name: getattr(row, name) for name in (
        "id", "server_id", "agent_id", "owner_id", "reviewer_id", "name", "state", "result", "error",
        "duration_ms", "created_at", "arguments",
    )}


def server_view(row, user):
    fields = {key: getattr(row, key) for key in ("id", "name", "kind", "enabled", "shared", "approval", "allowed")}
    if user.role == "admin":
        fields["url"] = row.url
        fields["has_key"] = row.kind == "builtin" or bool(row.key_ciphertext)
    fields["tools"] = [tool for name, tool in row.tools.items()
                       if user.role == "admin" or name in row.allowed]
    return fields


def get_server(db, key, locked=False):
    row = db.get(ToolServer, key, with_for_update=locked, populate_existing=locked)
    if not row:
        raise HTTPException(404, "MCP 服务不存在")
    return row


@router.get("/servers")
def list_servers(db: Db, identity: Identity, agent_id: UUID | None = None):
    user = identity[0]
    links = None
    if agent_id:
        agent = shared_agent(db.get(Agent, agent_id), user)
        if not agent.enabled:
            raise HTTPException(409, "智能体已停用")
        links = {}
        for link in db.scalars(select(AgentTool).where(AgentTool.agent_id == agent_id)):
            links.setdefault(link.server_id, set()).add(link.name)
    result = []
    for server in db.scalars(select(ToolServer).order_by(ToolServer.name).limit(200)):
        if not can_use(server, user) or (links is not None and server.id not in links):
            continue
        item = server_view(server, user)
        if links is not None:
            item["tools"] = [tool for tool in item["tools"]
                             if tool["name"] in links[server.id] and tool["name"] in server.allowed]
            if not item["tools"] or not server.enabled:
                continue
        result.append(item)
    return result


def save(db, row, form, admin):
    try:
        url = OPS_URL if form.kind == "builtin" else canonical_url("custom", form.url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    raw = form.api_key.get_secret_value() if form.api_key is not None else None
    if raw and (not raw.isascii() or not all(33 <= ord(char) <= 126 for char in raw)):
        raise HTTPException(422, "API Key 格式无效")
    moved = bool(row.kind and (row.url != url or row.kind != form.kind))
    if moved and row.key_ciphertext and not raw and not form.clear_key and form.kind != "builtin":
        raise HTTPException(422, "修改地址须重新填写或清除 API Key")
    reset = moved or bool(raw) or form.clear_key
    if reset and row.id and db.scalar(select(AgentTool.agent_id).where(AgentTool.server_id == row.id).limit(1)):
        raise HTTPException(409, "修改连接前请解除智能体授权")
    try:
        if form.kind == "builtin" or form.clear_key:
            row.key_ciphertext = None
        if raw and form.kind == "external":
            row.key_ciphertext = encrypt_key(raw)
    except UpstreamError as error:
        raise HTTPException(503, str(error)) from None
    row.tools = {} if reset else row.tools or {}
    if not reset and set(form.allowed) - row.tools.keys():
        raise HTTPException(422, "授权工具必须先由服务发现")
    row.allowed = [] if reset else sorted(set(form.allowed))
    row.kind, row.url, row.name = form.kind, url, form.name
    row.enabled, row.shared = form.enabled, form.shared
    row.approval = form.approval or form.kind == "external"
    db.add(row)
    db.commit()
    audit("mcp_server_saved", admin.id, row.id)
    return server_view(row, admin)


@router.post("/servers", status_code=201)
def create(form: ServerForm, db: Db, admin: Admin):
    return save(db, ToolServer(owner_id=admin.id), form, admin)


@router.put("/servers/{key}")
def update(key: UUID, form: ServerForm, db: Db, admin: Admin):
    return save(db, get_server(db, key, locked=True), form, admin)


@router.delete("/servers/{key}", status_code=204)
def remove(key: UUID, db: Db, admin: Admin):
    row = get_server(db, key)
    if db.scalar(select(AgentTool.agent_id).where(AgentTool.server_id == key).limit(1)):
        raise HTTPException(409, "请先解除智能体授权")
    db.delete(row)
    db.commit()
    audit("mcp_server_deleted", admin.id, key)


@router.post("/servers/{key}/test")
async def test_and_discover(key: UUID, db: Db, admin: Admin):
    row = get_server(db, key)
    settings = config(row)
    try:
        tools = await discover(settings)
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from None
    row = get_server(db, key, locked=True)
    if config(row) != settings:
        raise HTTPException(409, "连接设置已变更，请重新发现")
    unchanged = [name for name in row.allowed if name in tools and tools[name] == row.tools.get(name)]
    row.tools = tools
    row.allowed = unchanged
    db.commit()
    audit("mcp_tools_discovered", admin.id, key)
    return server_view(row, admin)


def permitted(db, user, server, name, agent_key):
    if not can_use(server, user) or not server.enabled or name not in server.allowed:
        raise HTTPException(404, "工具不可用或未获授权")
    if agent_key:
        agent = shared_agent(db.get(Agent, agent_key), user)
        if not agent.enabled or not db.get(AgentTool, (agent_key, server.id, name)):
            raise HTTPException(403, "智能体未获此工具授权")
    tool = server.tools.get(name)
    if not tool:
        raise HTTPException(409, "工具结构待重新发现")
    return tool


def approved_fingerprint(tool, agent_key):
    return fingerprint({"tool": tool, "agent": str(agent_key) if agent_key else None})


async def perform(db, row, settings, reviewed):
    call_id, tool, arguments = row.id, row.name, row.arguments
    db.commit()
    started = perf_counter()
    try:
        result = await execute(settings, tool, arguments, reviewed)
        state, failure = "success", None
    except UpstreamError as error:
        result, state, failure = None, "failed", str(error)
    row = db.get(ToolCall, call_id)
    row.state, row.error, row.result = state, failure, result
    row.duration_ms = round((perf_counter() - started) * 1000)
    row.arguments = None
    db.commit()
    audit("mcp_tool_finished", row.owner_id, row.id)
    return state_data(row)


@router.post("/servers/{key}/calls", status_code=201)
async def invoke(key: UUID, form: RequestCall, db: Db, identity: Identity):
    user = identity[0]
    server = get_server(db, key)
    tool = permitted(db, user, server, form.tool, form.agent_id)
    try:
        validate(tool, form.arguments)
    except UpstreamError as error:
        raise HTTPException(422, str(error)) from None
    pending = server.approval or server.kind == "external"
    row = ToolCall(owner_id=user.id, server_id=key, agent_id=form.agent_id, name=form.tool,
                   state="pending" if pending else "running", arguments=form.arguments,
                   fingerprint=approved_fingerprint(tool, form.agent_id))
    db.add(row)
    db.flush()
    audit("mcp_tool_requested", user.id, row.id)
    if pending:
        db.commit()
        return state_data(row)
    return await perform(db, row, config(server), tool)


@router.get("/calls")
def calls(db: Db, identity: Identity):
    user = identity[0]
    query = select(ToolCall).order_by(ToolCall.created_at.desc()).limit(100)
    if user.role != "admin":
        query = query.where(ToolCall.owner_id == user.id)
    return [state_data(row) for row in db.scalars(query)]


@router.post("/calls/{key}/review")
async def review(key: UUID, form: Review, db: Db, admin: Admin):
    row = db.get(ToolCall, key, with_for_update=True)
    if not row:
        raise HTTPException(404, "审批请求不存在")
    if row.state != "pending":
        raise HTTPException(409, "该请求已处理")
    row.reviewer_id = admin.id
    if not form.approve:
        row.state, row.arguments = "rejected", None
        db.commit()
        audit("mcp_tool_rejected", admin.id, key)
        return state_data(row)
    requester = db.get(User, row.owner_id)
    if not requester or not requester.is_active:
        raise HTTPException(409, "请求者已停用")
    server = get_server(db, row.server_id)
    current = permitted(db, requester, server, row.name, row.agent_id)
    if approved_fingerprint(current, row.agent_id) != row.fingerprint:
        raise HTTPException(409, "工具结构或智能体授权已变更，请重新申请")
    row.state = "running"
    audit("mcp_tool_approved", admin.id, key)
    return await perform(db, row, config(server), current)
