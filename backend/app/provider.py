import asyncio
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

PROVIDERS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


class UpstreamError(Exception):
    pass


def secret_store():
    key = os.environ.get("PLATFORM_MODEL_KEY")
    if not key:
        raise UpstreamError("模型密钥存储尚未配置")
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise UpstreamError("模型密钥存储配置无效") from None


def encrypt_key(secret):
    return secret_store().encrypt(secret.encode()).decode()


def decrypt_key(ciphertext):
    if not ciphertext:
        return None
    try:
        return secret_store().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        raise UpstreamError("模型密钥不可读取") from None


def canonical_url(provider, value):
    if provider in PROVIDERS:
        expected = PROVIDERS[provider]
        if value and value.rstrip("/") != expected:
            raise ValueError("使用其他地址时请选择自定义服务商")
        return expected

    raw = (value or "").rstrip("/")
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        valid = (parts.scheme == "https" and re.fullmatch(r"[a-z0-9.-]+", host)
                 and "." in host and not host.endswith(".") and ".." not in host
                 and parts.netloc in {host, f"{host}:443"} and not parts.query
                 and not parts.fragment and re.fullmatch(r"(/[a-zA-Z0-9_-]+)*", parts.path)
                 and raw in {f"https://{host}{parts.path}", f"https://{host}:443{parts.path}"})
        if valid:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return f"https://{host}{parts.path}"
    except ValueError:
        pass
    raise ValueError("自定义地址须使用公开 HTTPS 域名和 443 端口")


def public_ip(address):
    parsed = ipaddress.ip_address(address)
    # An IPv4-mapped address is classified by its underlying IPv4 destination.
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    return (parsed.is_global and not parsed.is_multicast and not parsed.is_reserved
            and not (isinstance(parsed, ipaddress.IPv6Address) and
                     (parsed.is_site_local or parsed not in GLOBAL_UNICAST
                      or any(parsed in network for network in TRANSITION_NETWORKS))))


TRANSITION_NETWORKS = tuple(map(ipaddress.ip_network, ("64:ff9b::/96", "64:ff9b:1::/48",
                                                      "2002::/16", "2001::/32")))
GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")


async def public_destination(host):
    try:
        options = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=4
        )
        addresses = {item[4][0] for item in options}
        if not addresses or not all(public_ip(address) for address in addresses):
            raise UpstreamError("模型域名解析到了受限网络")
    except (TimeoutError, OSError, ValueError):
        raise UpstreamError("模型域名无法解析") from None
    # Prefer IPv4 on hosts with IPv6 DNS but no usable IPv6 egress.
    target = sorted(addresses, key=lambda value: (":" in value, value))[0]
    return f"[{target}]" if ":" in target else target


async def pinned_url(base):
    parts = urlsplit(base)
    host = parts.hostname
    authority = await public_destination(host)
    return f"https://{authority}{parts.path}/chat/completions", host


def usage_from(data):
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    names = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens",
             "total_tokens": "total_tokens"}
    return {names[key]: value for key, value in usage.items()
            if key in names and type(value) is int and 0 <= value < 2**31}


def status_error(status):
    if status in (401, 403):
        return "模型服务拒绝了凭据或访问权限"
    if status == 429:
        return "模型服务限流或额度不足"
    return f"模型服务返回 HTTP {status}"


async def model_events(config, messages, stream=True):
    try:
        base = canonical_url(config["provider"], config["base_url"])
        url, host = await pinned_url(base)
        secret = decrypt_key(config["key_ciphertext"])
        if not secret and config["provider"] != "custom":
            raise UpstreamError("请配置模型 API Key")
        headers = {"Host": host}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        payload = {"model": config["model"], "messages": messages, "stream": stream,
                   "temperature": config["temperature"], "max_tokens": config["max_tokens"]}
        if stream and config["provider"] != "custom":
            payload["stream_options"] = {"include_usage": True}
        async with asyncio.timeout(config["timeout"]):
            timeout = httpx.Timeout(config["timeout"], connect=5.0, pool=5.0)
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload,
                                         extensions={"sni_hostname": host}) as response:
                    if response.status_code != 200:
                        raise UpstreamError(status_error(response.status_code))
                    if not stream:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 1_000_000:
                                raise UpstreamError("模型响应超过限制")
                        data = json.loads(body)
                        yield "usage", usage_from(data)
                        content = data["choices"][0]["message"]["content"]
                        if isinstance(content, str) and content:
                            yield "delta", content
                        return

                    async for line in response.aiter_lines():
                        if len(line) > 1_000_000:
                            raise UpstreamError("模型响应超过限制")
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            return
                        data = json.loads(raw)
                        if "error" in data:
                            raise UpstreamError("模型服务报告生成失败")
                        usage = usage_from(data)
                        if usage:
                            yield "usage", usage
                        for choice in data.get("choices", [])[:1]:
                            content = choice.get("delta", {}).get("content")
                            if isinstance(content, str) and content:
                                yield "delta", content
                    raise UpstreamError("模型流连接提前结束")
    except (TimeoutError, httpx.TimeoutException):
        raise UpstreamError("模型请求超时") from None
    except httpx.HTTPError:
        raise UpstreamError("无法安全连接模型服务") from None
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise UpstreamError("模型服务响应格式不兼容") from None
