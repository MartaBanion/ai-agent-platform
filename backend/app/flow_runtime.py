import asyncio
import copy
import hashlib
import json
import os
from functools import lru_cache
from threading import Lock
from time import time
from uuid import UUID

import httpx
import jwt
from starlette.concurrency import run_in_threadpool

from app.provider import UpstreamError, canonical_url, decrypt_key, pinned_url

URL = os.environ.get("LANGFLOW_BASE_URL", "http://langflow:7860").rstrip("/")
PORT = int(os.environ.get("LANGFLOW_EDITOR_PORT", "7860"))
MODEL_PROVIDERS = {"openai": "openai", "deepseek": "deepseek"}
MODEL_KEY_VARIABLE = "PLATFORM-MODEL-API-KEY"
_login_lock = Lock()
_token = ""
_token_expiry = 0.0


def credentials():
    password = os.environ.get("PLATFORM_LANGFLOW_SERVICE_PASSWORD")
    if not password:
        raise UpstreamError("请配置 Langflow 服务账号")
    return {"username": "platform_flow_service", "password": password}


def checked(response):
    if response.status_code not in (200, 201):
        raise UpstreamError(f"Langflow 请求失败（HTTP {response.status_code}）")
    return response


def service_token():
    global _token, _token_expiry
    with _login_lock:
        if time() < _token_expiry:
            return _token
        try:
            with httpx.Client(base_url=URL, timeout=8, trust_env=False) as client:
                login = checked(client.post("/api/v1/login", data=credentials())).json()
            token = login["access_token"]
            expires = jwt.decode(token, options={"verify_signature": False})["exp"]
            _token_expiry = min(float(expires) - 15, time() + 600)
            _token = token
            return token
        except (httpx.HTTPError, jwt.InvalidTokenError, ValueError, KeyError, TypeError):
            raise UpstreamError("无法验证 Langflow 服务身份") from None


def rejected_token(token):
    global _token_expiry
    with _login_lock:
        if token == _token:
            _token_expiry = 0


def engine_request(method, path, **kwargs):
    try:
        with httpx.Client(base_url=URL, timeout=12, trust_env=False) as client:
            token = service_token()
            client.headers["Authorization"] = "Bearer " + token
            response = client.request(method, path, **kwargs)
            if response.status_code == 401:
                rejected_token(token)
            return checked(response).json()
    except (httpx.HTTPError, ValueError, KeyError):
        raise UpstreamError("无法访问 Langflow 服务") from None


@lru_cache(maxsize=2)
def trusted_graph(kind):
    if kind not in {"echo", "prompt"}:
        raise UpstreamError("未知的工作流模板")
    examples = engine_request("GET", "/api/v1/flows/basic_examples/")
    example = next((item["data"] for item in examples if item["name"] == "Basic Prompting"), None)
    if not example:
        raise UpstreamError("Langflow 缺少受支持的内置模板")
    graph = copy.deepcopy(example)
    allowed = {"ChatInput", "ChatOutput"}
    if kind == "prompt":
        allowed.add("LanguageModelComponent")
    graph["nodes"] = [node for node in graph["nodes"] if node["data"].get("type") in allowed]
    nodes = {node["data"]["type"]: node for node in graph["nodes"]}
    if set(nodes) != allowed or len(graph["nodes"]) != len(allowed):
        raise UpstreamError("Langflow 内置模板结构变更")
    for role in ("ChatInput", "ChatOutput"):
        template = nodes[role]["data"]["node"]["template"]
        template["should_store_message"]["value"] = False
    if kind == "echo":
        first = next(edge for edge in graph["edges"] if edge["source"] == nodes["ChatInput"]["id"])
        last = next(edge for edge in graph["edges"] if edge["target"] == nodes["ChatOutput"]["id"])
        last["source"], last["sourceHandle"] = first["source"], first["sourceHandle"]
        last["data"]["sourceHandle"] = first["data"]["sourceHandle"]
        last["id"] = f"edge-{last['source']}-{last['target']}"
        graph["edges"] = [last]
    else:
        ids = {node["id"] for node in graph["nodes"]}
        graph["edges"] = [edge for edge in graph["edges"] if edge["source"] in ids and edge["target"] in ids]
    return graph


def graph_digest(graph):
    return hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def security_shape(graph):
    graph = copy.deepcopy(graph)
    graph.pop("viewport", None)
    for node in graph.get("nodes", []):
        for field in ("position", "positionAbsolute", "selected", "dragging", "measured", "width", "height"):
            node.pop(field, None)
    for edge in graph.get("edges", []):
        edge.pop("selected", None)
    return graph


def approved(graph, kind):
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise UpstreamError("工作流图格式无效")
    try:
        if graph_digest(security_shape(graph)) == graph_digest(security_shape(trusted_graph(kind))):
            return
    except (TypeError, AttributeError):
        pass
    raise UpstreamError("流程与已批准模板不匹配，请检查组件、参数和连线")


def verify_flow(native, kind):
    if any(native.get(field) for field in ("webhook", "mcp_enabled", "a2a_enabled", "is_component")):
        raise UpstreamError("请关闭工作流的外部发布入口")
    if native.get("access_type") != "PRIVATE":
        raise UpstreamError("需要私有 Langflow 工作流")
    graph = native.get("data")
    approved(graph, kind)
    return graph


def native_text(payload):
    for group in payload.get("outputs", []):
        for vertex in group.get("outputs", []):
            message = vertex.get("results", {}).get("message")
            if isinstance(message, dict) and not message.get("error"):
                content = message.get("text", message.get("data", {}).get("text"))
                if isinstance(content, str):
                    return content
    return ""


def native_usage(payload):
    fields = {"input_tokens", "output_tokens", "total_tokens"}
    result = {}
    for group in payload.get("outputs", []):
        for vertex in group.get("outputs", []):
            usage = vertex.get("token_usage")
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if key in fields and type(value) is int and 0 <= value < 2**31:
                        result[key] = value
    return result


def flow_tweaks(graph, config, prompt):
    if config["provider"] not in MODEL_PROVIDERS:
        raise UpstreamError("当前 Langflow 模型模板支持 OpenAI 和 DeepSeek")
    key = decrypt_key(config["key_ciphertext"])
    if not key:
        raise UpstreamError("请配置关联模型的 API Key")
    component = next(node["id"] for node in graph["nodes"]
                     if node["data"]["type"] == "LanguageModelComponent")
    return ({component: {"provider": MODEL_PROVIDERS[config["provider"]], "model_name": config["model"],
                         "api_key": {"value": MODEL_KEY_VARIABLE, "load_from_db": True},
                         "temperature": config["temperature"], "max_tokens": config["max_tokens"],
                         "system_message": prompt, "stream": True}},
            {"X-Langflow-Global-Var-" + MODEL_KEY_VARIABLE: key})


async def flow_events(engine_id: UUID, kind, digest, input_value, session_id, config=None, prompt=""):
    try:
        budget = config["timeout"] if config else 45
        async with asyncio.timeout(budget):
            timeout = httpx.Timeout(budget, connect=5.0, pool=5.0)
            async with httpx.AsyncClient(base_url=URL, timeout=timeout, trust_env=False) as client:
                token = await run_in_threadpool(service_token)
                client.headers["Authorization"] = "Bearer " + token
                verified = await client.get(f"/api/v1/flows/{engine_id}")
                if verified.status_code == 401:
                    await run_in_threadpool(rejected_token, token)
                native = checked(verified).json()
                # Execution is tied to an approved snapshot. Native changes require a new sync.
                graph = native.get("data")
                if graph_digest(graph) != digest or native.get("access_type") != "PRIVATE":
                    raise UpstreamError("工作流版本已变更，请同步并审核")
                if any(native.get(field) for field in ("webhook", "mcp_enabled", "a2a_enabled", "is_component")):
                    raise UpstreamError("请关闭工作流的外部发布入口")
                payload = {"input_value": input_value, "input_type": "chat", "output_type": "chat",
                           "session_id": str(session_id)}
                headers = {}
                if kind == "prompt":
                    if not config:
                        raise UpstreamError("请先关联模型")
                    if config["provider"] not in MODEL_PROVIDERS:
                        raise UpstreamError("当前 Langflow 模型模板支持 OpenAI 和 DeepSeek")
                    await pinned_url(canonical_url(config["provider"], config["base_url"]))
                    payload["tweaks"], headers = flow_tweaks(graph, config, prompt)
                async with client.stream("POST", f"/api/v1/run/session/{engine_id}",
                                         params={"stream": "true"}, json=payload, headers=headers) as response:
                    if response.status_code == 401:
                        await run_in_threadpool(rejected_token, token)
                    checked(response)
                    latest = ""
                    emitted = False
                    error_event = False
                    async for line in response.aiter_lines():
                        if len(line) > 2_000_000:
                            raise UpstreamError("Langflow 响应超过限制")
                        line = line.removeprefix("data:").strip()
                        if not line or not line.startswith("{"):
                            continue
                        event = json.loads(line)
                        body = event.get("data") or {}
                        kind_name = event.get("event")
                        if kind_name == "token":
                            chunk = body.get("chunk", body.get("text"))
                            if isinstance(chunk, str) and chunk:
                                emitted = True
                                yield "delta", chunk
                        if kind_name in {"add_message", "end"} and not emitted:
                            if body.get("error"):
                                error_event = True
                            if kind_name == "end":
                                latest = native_text(body.get("result") or body) or latest
                            elif body.get("sender") == "Machine" and isinstance(body.get("text"), str):
                                latest = body["text"]
                        if kind_name == "error":
                            raise UpstreamError("Langflow 工作流执行失败")
                        if kind_name == "end":
                            if error_event:
                                raise UpstreamError("Langflow 工作流执行失败")
                            usage = native_usage(body.get("result") or body)
                            if usage:
                                yield "usage", usage
                            if latest and not emitted:
                                yield "delta", latest
                            return
                    if error_event:
                        raise UpstreamError("Langflow 工作流执行失败")
                    raise UpstreamError("Langflow 工作流连接提前结束")
    except (TimeoutError, httpx.TimeoutException):
        raise UpstreamError("Langflow 工作流执行超时") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise UpstreamError("Langflow 响应无效或连接失败") from None
