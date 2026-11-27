from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.ai_access import owned, require_builder
from app.ai_models import Execution, Workflow, WorkflowVersion
from app.execution import begin, serialize, stream_response
from app.flow_runtime import PORT, approved, engine_request, flow_events, graph_digest, trusted_graph, verify_flow
from app.model_api import model_config, selected
from app.provider import UpstreamError
from app.schemas import Input, Name
from app.security import Db, Identity, audit

router = APIRouter(prefix="/workflows", tags=["工作流"])


class Register(Input):
    name: Name
    description: str = Field("", max_length=1000)
    kind: Literal["echo", "prompt"]
    document: dict | None = None


class Attach(Input):
    engine_id: UUID
    kind: Literal["echo", "prompt"]


class Run(Input):
    text: str = Field(min_length=1, max_length=12000)
    model_id: UUID | None = None


def workflow_view(row):
    return {name: getattr(row, name) for name in ("id", "engine_id", "name", "description", "kind")}


def upstream():
    return HTTPException(502, "Langflow 服务暂不可用")


@router.get("")
def list_workflows(db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    statement = select(Workflow).order_by(Workflow.name)
    if user.role != "admin":
        statement = statement.where(Workflow.owner_id == user.id)
    return [workflow_view(row) for row in db.scalars(statement)]


@router.get("/discovery")
def discover(db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    keys = set(db.scalars(select(Workflow.engine_id).where(Workflow.owner_id == user.id)))
    try:
        data = engine_request("GET", "/api/v1/flows/", params={"header_flows": True, "page": 1, "size": 100})
    except UpstreamError:
        raise upstream() from None
    items = data if isinstance(data, list) else data.get("items", [])
    return [{"id": row["id"], "name": row["name"]} for row in items
            if user.role == "admin" or UUID(row["id"]) in keys]


@router.get("/editor")
def editor(identity: Identity):
    require_builder(identity[0])
    return {"url": f"http://127.0.0.1:{PORT}/"}


def persist_native(db, user, native, kind):
    if db.scalar(select(Workflow.id).where(Workflow.engine_id == native["id"])):
        raise HTTPException(409, "该工作流已关联")
    try:
        graph = verify_flow(native, kind)
    except UpstreamError as error:
        raise HTTPException(422, str(error)) from None
    flow = Workflow(owner_id=user.id, engine_id=UUID(native["id"]), name=native["name"][:120],
                    description=(native.get("description") or "")[:1000], kind=kind, digest=graph_digest(graph))
    db.add(flow)
    try:
        db.flush()
        db.add(WorkflowVersion(workflow_id=flow.id, number=1, digest=flow.digest, data=graph))
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "该工作流已关联") from None
    audit("workflow_registered", user.id, flow.id)
    return workflow_view(flow)


@router.post("", status_code=201)
def create(payload: Register, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    if payload.document is not None:
        try:
            approved(payload.document.get("data"), payload.kind)
        except UpstreamError as error:
            raise HTTPException(422, str(error)) from None
    try:
        graph = trusted_graph(payload.kind)
        native = engine_request("POST", "/api/v1/flows/", json={
            "name": payload.name, "description": payload.description, "data": graph,
            "access_type": "PRIVATE", "webhook": False, "mcp_enabled": False, "a2a_enabled": False,
        })
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from None
    return persist_native(db, user, native, payload.kind)


@router.post("/attach", status_code=201)
def attach(payload: Attach, db: Db, identity: Identity):
    user = identity[0]
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可关联已存在的引擎工作流")
    try:
        native = engine_request("GET", f"/api/v1/flows/{payload.engine_id}")
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from None
    return persist_native(db, user, native, payload.kind)


@router.post("/{key}/sync")
def sync(key: UUID, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    workflow = owned(db.get(Workflow, key, with_for_update=True), user)
    try:
        native = engine_request("GET", f"/api/v1/flows/{workflow.engine_id}")
        graph = verify_flow(native, workflow.kind)
    except UpstreamError as error:
        raise HTTPException(422, str(error)) from None
    digest = graph_digest(graph)
    if digest != workflow.digest:
        number = db.scalar(select(func.max(WorkflowVersion.number)).where(WorkflowVersion.workflow_id == key))
        db.add(WorkflowVersion(workflow_id=key, number=number + 1, digest=digest, data=graph))
        workflow.digest = digest
    workflow.name = native["name"][:120]
    workflow.description = (native.get("description") or "")[:1000]
    db.commit()
    audit("workflow_synchronized", user.id, key)
    return workflow_view(workflow)


@router.get("/{key}/versions")
def versions(key: UUID, db: Db, identity: Identity):
    require_builder(identity[0])
    owned(db.get(Workflow, key), identity[0])
    statement = select(WorkflowVersion).where(WorkflowVersion.workflow_id == key).order_by(WorkflowVersion.number.desc())
    return [{"number": row.number, "digest": row.digest, "created_at": row.created_at}
            for row in db.scalars(statement)]


@router.get("/{key}/export")
def export(key: UUID, db: Db, identity: Identity):
    require_builder(identity[0])
    workflow = owned(db.get(Workflow, key), identity[0])
    version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == key)
                        .order_by(WorkflowVersion.number.desc()).limit(1))
    return {"name": workflow.name, "description": workflow.description, "data": version.data}


@router.get("/{key}/history")
def history(key: UUID, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    owned(db.get(Workflow, key), user)
    statement = (select(Execution).where(Execution.workflow_id == key)
                 .where(or_(Execution.owner_id == user.id, user.role == "admin"))
                 .order_by(Execution.created_at.desc()).limit(50))
    return [serialize(row) for row in db.scalars(statement)]


@router.post("/{key}/run")
def run(key: UUID, payload: Run, db: Db, identity: Identity):
    user = identity[0]
    require_builder(user)
    workflow = owned(db.get(Workflow, key), user)
    model = selected(db, payload.model_id) if workflow.kind == "prompt" else None
    execution = begin(db, user, "workflow", workflow=key, model=model.id if model else None)
    events = flow_events(workflow.engine_id, workflow.kind, workflow.digest, payload.text, uuid4(),
                         model_config(model) if model else None)
    execution_id = execution.id
    db.commit()
    return stream_response(events, execution_id)
