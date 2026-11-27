import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.auth_api import router as auth_router
from app.agent_api import router as agent_router
from app.agent_resources import router as agent_resources_router
from app.chat_api import router as chat_router
from app.execution import router as execution_router
from app.knowledge_api import router as knowledge_router
from app.mcp_api import router as mcp_router
from app.model_api import router as model_router
from app.workflow_api import router as workflow_router
from app.db import engine
from app.langflow import langflow
from app.models import User
from app.security import Db, Identity
from app.users_api import router as users_router


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"time": datetime.now(UTC).isoformat(), "level": record.levelname, "event": record.msg}
        for key in ("request_id", "method", "route", "status", "duration_ms", "actor_id", "target_id", "error_type"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("platform")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
app = FastAPI(title="企业 AI 智能体平台", docs_url=None, redoc_url=None, openapi_url=None)
api = APIRouter(prefix="/api/v1")
api.include_router(auth_router)
api.include_router(users_router)
api.include_router(model_router)
api.include_router(agent_router)
api.include_router(chat_router)
api.include_router(workflow_router)
api.include_router(execution_router)
api.include_router(knowledge_router)
api.include_router(mcp_router)
api.include_router(agent_resources_router)


def error_response(request, status, code, message, headers=None):
    return JSONResponse({"error": {"code": code, "message": message,
                                   "request_id": request.state.request_id}}, status, headers=headers)


@app.middleware("http")
async def request_context(request: Request, call_next):
    started = perf_counter()
    request.state.request_id = uuid4().hex
    try:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            request.headers.get("x-platform-request") != "1"
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            response = error_response(request, 403, "request_origin", "请求来源无效")
        else:
            response = await call_next(request)
    except Exception as error:
        logger.error("request_failed", extra={"request_id": request.state.request_id,
                                              "error_type": type(error).__name__})
        response = error_response(request, 500, "internal_error", "服务发生异常")
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    route = request.scope.get("route")
    logger.info("request", extra={"request_id": request.state.request_id, "method": request.method,
                                  "route": getattr(route, "path", "unmatched"),
                                  "status": response.status_code, "duration_ms": round((perf_counter() - started) * 1000)})
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    return error_response(request, error.status_code, f"http_{error.status_code}", error.detail, error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    return error_response(request, 422, "invalid_input", "请求参数不符合要求")


@app.exception_handler(SQLAlchemyError)
async def db_error(request: Request, error: SQLAlchemyError):
    logger.error("database_error", extra={"request_id": request.state.request_id,
                                         "error_type": type(error).__name__})
    return error_response(request, 503, "database_unavailable", "数据库暂不可用")


@api.get("/health")
def health(request: Request):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return error_response(request, 503, "database_unavailable", "数据库暂不可用")
    return {"status": "healthy"}


@api.get("/system/langflow")
def engine_health(identity: Identity):
    return langflow.health()


@api.get("/system/overview")
def overview(db: Db, identity: Identity):
    user, _ = identity
    counts = None
    db.execute(text("SELECT 1"))
    if user.role == "admin":
        total, active = db.execute(select(func.count(User.id), func.count(User.id).filter(User.is_active))).one()
        counts = {"total": total, "active": active}
    return {"services": {"api": "available", "database": "available", "langflow": langflow.health()},
            "users": counts, "checked_at": datetime.now(UTC)}


app.include_router(api)
