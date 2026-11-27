import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai_models import Conversation, Execution, Message
from app.db import engine
from app.provider import UpstreamError
from app.security import Db, Identity

router = APIRouter(prefix="/executions", tags=["执行"])
active: dict[UUID, asyncio.Event] = {}


@router.post("/{key}/stop", status_code=204)
async def stop(key: UUID, db: Db, identity: Identity):
    row = await run_in_threadpool(db.get, Execution, key)
    if not row or row.owner_id != identity[0].id:
        raise HTTPException(404, "执行记录不存在")
    if signal := active.get(key):
        signal.set()


class Stopped(Exception):
    pass


async def next_event(queue, signal):
    step = asyncio.create_task(queue.get())
    stop_waiter = asyncio.create_task(signal.wait())
    try:
        finished, _ = await asyncio.wait((step, stop_waiter), return_when=asyncio.FIRST_COMPLETED)
        if stop_waiter in finished:
            raise Stopped
        return step.result()
    finally:
        for task in (step, stop_waiter):
            if not task.done():
                task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(step, stop_waiter, return_exceptions=True)


async def pump(events, queue):
    try:
        async for event in events:
            await queue.put(event)
    except UpstreamError as error:
        await queue.put(("failed", str(error)))
    except Exception:
        await queue.put(("failed", "执行发生异常"))
    else:
        await queue.put(("end", None))
    finally:
        await events.aclose()


def begin(db, user, source, *, conversation=None, model=None, agent=None, workflow=None):
    execution = Execution(owner_id=user.id, source=source, status="running", conversation_id=conversation,
                          model_id=model, agent_id=agent, workflow_id=workflow)
    db.add(execution)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(409, "当前会话已有生成任务或资源已变更") from None
    return execution


def finish(key, status, started, output, usage, error=None):
    with Session(engine) as db:
        row = db.get(Execution, key)
        if not row:
            return
        conversation = (db.get(Conversation, row.conversation_id, with_for_update=True)
                        if row.conversation_id else None)
        row.status = status
        row.duration_ms = round((perf_counter() - started) * 1000)
        row.error = error
        for field, value in usage.items():
            setattr(row, field, value)
        if output and status == "success" and conversation:
            db.add(Message(conversation_id=conversation.id, role="assistant", content=output))
            conversation.updated_at = datetime.now(UTC)
        db.commit()


def serialize(row):
    return {field: getattr(row, field) for field in (
        "id", "source", "status", "error", "duration_ms", "created_at",
        "input_tokens", "output_tokens", "total_tokens",
    )}


def frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_response(events, key):
    async def generate():
        started = perf_counter()
        signal = asyncio.Event()
        active[key] = signal
        queue = asyncio.Queue(maxsize=8)
        producer = asyncio.create_task(pump(events, queue))
        content = ""
        usage = {}
        status, reason = "cancelled", "客户端停止生成"
        try:
            yield frame("start", {"id": str(key)})
            while True:
                event, value = await next_event(queue, signal)
                if event == "end":
                    break
                if event == "failed":
                    raise UpstreamError(value)
                if event == "usage":
                    usage.update(value)
                else:
                    content += value
                    if len(content) > 120_000:
                        raise UpstreamError("生成内容超过长度限制")
                    yield frame("delta", {"text": value})
            if not content:
                raise UpstreamError("服务未返回文本内容")
            status, reason = "success", None
        except UpstreamError as error:
            status, reason = "failed", str(error)
        except Stopped:
            status, reason = "cancelled", "已停止生成，可重试最后一条消息"
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            status, reason = "failed", "执行发生异常"
        finally:
            active.pop(key, None)
            with anyio.CancelScope(shield=True):
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
                await run_in_threadpool(finish, key, status, started, content, usage, reason)
        if status in {"failed", "cancelled"}:
            yield frame("error", {"message": reason})
        else:
            yield frame("done", {"usage": usage})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})


async def probe_response(events, key: UUID):
    started = perf_counter()
    text, usage = "", {}
    try:
        async for event, value in events:
            if event == "delta":
                text += value
            else:
                usage.update(value)
        if not text:
            raise UpstreamError("服务未返回文本内容")
    except UpstreamError as error:
        await run_in_threadpool(finish, key, "failed", started, "", usage, str(error))
        raise HTTPException(502, str(error)) from None
    except (asyncio.CancelledError, GeneratorExit):
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(finish, key, "cancelled", started, "", usage, "客户端取消")
        raise
    await run_in_threadpool(finish, key, "success", started, text, usage)
    return {"status": "success", "duration_ms": round((perf_counter() - started) * 1000), "usage": usage}
