import asyncio
import hashlib
import json
import os
import re
from contextlib import asynccontextmanager

import httpx
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.provider import UpstreamError, canonical_url, decrypt_key, public_destination

OPS_URL = "http://ops:8001/mcp"
MAX_WIRE = 512_000
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
OPS_TOOLS = {"current_time", "system_state", "resource_metrics", "service_health",
             "network_calculation", "connectivity_check"}


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        count = 0
        async for chunk in self.stream:
            count += len(chunk)
            if count > MAX_WIRE:
                raise UpstreamError("MCP 响应超过大小限制")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class FixedTransport(httpx.AsyncBaseTransport):
    def __init__(self, url, authority):
        self.url = httpx.URL(url)
        self.authority = authority
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        if request.url != self.url:
            raise UpstreamError("MCP 请求地址偏离注册地址")
        request.headers["Accept-Encoding"] = "identity"
        if self.authority:
            host = self.url.host
            request.headers["Host"] = host
            request.extensions["sni_hostname"] = host
            request.url = httpx.URL(f"https://{self.authority}{self.url.raw_path.decode('ascii')}")
        response = await self.transport.handle_async_request(request)
        if 300 <= response.status_code < 400 or response.headers.get("content-encoding", "identity") != "identity":
            await response.aclose()
            raise UpstreamError("MCP 服务器返回重定向或不支持的响应编码")
        response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.transport.aclose()


def schema_depth(value, depth=0):
    if depth > 12:
        raise ValueError()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef", "pattern", "patternProperties", "format"}:
                raise ValueError()
            schema_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            schema_depth(item, depth + 1)


def checked_schema(schema):
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError()
    if len(json.dumps(schema, ensure_ascii=False)) > 16_000:
        raise ValueError()
    schema_depth(schema)
    if not isinstance(schema.get("properties", {}), dict):
        raise ValueError()
    restricted = {**schema, "additionalProperties": False}
    Draft202012Validator.check_schema(restricted)
    return restricted


def validate(tool, arguments):
    try:
        if len(json.dumps(arguments, ensure_ascii=False)) > 12_000:
            raise ValueError()
        Draft202012Validator(tool["schema"]).validate(arguments)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise UpstreamError("工具参数不符合已审核结构") from None


def fingerprint(tool):
    return hashlib.sha256(json.dumps(tool, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[已脱敏]") if secret else value
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {redact(name, secret): redact(item, secret) for name, item in value.items()}
    return value


def config(row):
    return row.kind, row.url, row.key_ciphertext


@asynccontextmanager
async def session(configuration):
    kind, url, ciphertext = configuration
    try:
        async with asyncio.timeout(12):
            if kind == "builtin":
                if url != OPS_URL:
                    raise UpstreamError("内置运维地址配置异常")
                secret, authority = os.environ["PLATFORM_MCP_KEY"], None
            else:
                url = canonical_url("custom", url)
                authority = await public_destination(httpx.URL(url).host)
                secret = decrypt_key(ciphertext)
            headers = {"Authorization": "Bearer " + secret} if secret else {}
            async with httpx.AsyncClient(transport=FixedTransport(url, authority), headers=headers,
                                         follow_redirects=False, trust_env=False, timeout=10) as client:
                async with streamable_http_client(url, http_client=client) as (receive, send, _):
                    async with ClientSession(receive, send) as connection:
                        await connection.initialize()
                        yield connection, secret
    except UpstreamError:
        raise
    except TimeoutError:
        raise UpstreamError("MCP 服务请求超时") from None
    except Exception:
        raise UpstreamError("MCP 服务连接或协议请求失败") from None


async def tool_list(connection, secret, kind):
    tools = {}
    cursor = None
    for _ in range(5):
        response = await connection.list_tools(cursor=cursor)
        for row in response.tools:
            if len(tools) >= 50:
                return tools
            if not IDENTIFIER.fullmatch(row.name):
                continue
            if kind == "builtin" and row.name not in OPS_TOOLS:
                continue
            try:
                schema = checked_schema(redact(row.inputSchema, secret))
            except (ValueError, SchemaError, RecursionError):
                continue
            tools[row.name] = {"name": row.name, "description": redact((row.description or "")[:1000], secret),
                               "schema": schema}
        cursor = response.nextCursor
        if not cursor:
            break
    return tools


async def discover(configuration):
    async with session(configuration) as (connection, secret):
        return await tool_list(connection, secret, configuration[0])


async def execute(configuration, name, arguments, reviewed):
    async with session(configuration) as (connection, secret):
        if configuration[0] == "external":
            live = await tool_list(connection, secret, configuration[0])
            if live.get(name) != reviewed:
                raise UpstreamError("工具结构已变更，请重新发现和授权")
        response = await connection.call_tool(name, arguments)
        if response.isError:
            raise UpstreamError("工具返回执行错误")
        structured = response.structuredContent
        if isinstance(structured, dict):
            value = {"structured": redact(structured, secret)}
        else:
            value = {"text": [redact(item.text, secret) for item in response.content if item.type == "text"][:10]}
        if len(json.dumps(value, ensure_ascii=False)) > 24_000:
            raise UpstreamError("工具结果超过显示限制")
        return value
