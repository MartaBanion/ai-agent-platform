"""Private MCP service for bounded operational diagnostics."""

import hmac
import ipaddress
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import StringConstraints
from starlette.responses import PlainTextResponse

KEY = os.environ["PLATFORM_MCP_KEY"]
TARGETS = {"platform_api": "http://backend:8000/api/v1/health"}
Diagnostic = dict[str, str | int | bool | None]
mcp = FastMCP("企业运维工具", stateless_http=True, json_response=True,
              transport_security=TransportSecuritySettings(
                  enable_dns_rebinding_protection=True,
                  allowed_hosts=["ops:8001", "127.0.0.1:8001"], allowed_origins=[]))


@mcp.tool()
def current_time(zone: Literal["UTC", "Asia/Shanghai"] = "Asia/Shanghai") -> Diagnostic:
    """Read the current time in one of the configured time zones."""
    return {"zone": zone, "datetime": datetime.now(ZoneInfo(zone)).isoformat()}


@mcp.tool()
def system_state() -> Diagnostic:
    """Identify the isolated container environment."""
    return {"scope": "ops_container", "platform": "linux", "permissions": "read_only_diagnostics"}


def cgroup(filename):
    try:
        return Path("/sys/fs/cgroup", filename).read_text().strip()
    except OSError:
        return None


@mcp.tool()
def resource_metrics() -> Diagnostic:
    """Read container cgroup CPU and memory and /tmp filesystem usage."""
    statistics = cgroup("cpu.stat") or ""
    cpu_usage = next((int(line.split()[1]) for line in statistics.splitlines()
                      if line.startswith("usage_usec ")), None)
    memory = cgroup("memory.current")
    limit = cgroup("memory.max")
    disk = shutil.disk_usage("/tmp")
    return {"scope": "ops_container", "cpu_usage_microseconds": cpu_usage,
            "cpu_quota_and_period": cgroup("cpu.max"),
            "memory_used_bytes": int(memory) if memory and memory.isdigit() else None,
            "memory_limit_bytes": int(limit) if limit and limit.isdigit() else None,
            "disk_scope": "container_tmpfs", "disk_total_bytes": disk.total, "disk_free_bytes": disk.free}


@mcp.tool()
def network_calculation(cidr: Annotated[str, StringConstraints(max_length=80)]) -> Diagnostic:
    """Calculate a CIDR range without accessing a network."""
    network = ipaddress.ip_network(cidr, strict=False)
    return {"network": str(network), "version": network.version, "prefix": network.prefixlen,
            "start": str(network.network_address), "end": str(network.broadcast_address),
            "addresses": str(network.num_addresses)}


@mcp.tool()
async def service_health(target: Literal["platform_api"] = "platform_api") -> Diagnostic:
    """Read the health of a fixed internal test service."""
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False, follow_redirects=False) as client:
            response = await client.get(TARGETS[target])
        return {"target": target, "healthy": response.status_code == 200, "http_status": response.status_code}
    except httpx.HTTPError:
        return {"target": target, "healthy": False, "http_status": None}


@mcp.tool()
async def connectivity_check(target: Literal["platform_api"] = "platform_api") -> Diagnostic:
    """Check reachability only for the fixed allowlisted platform test endpoint."""
    outcome = await service_health(target)
    return {"target": target, "reachable": outcome["http_status"] is not None,
            "http_status": outcome["http_status"]}


transport = mcp.streamable_http_app()


async def app(scope, receive, send):
    if scope["type"] == "http":
        if scope["path"] == "/health" and scope["method"] == "GET":
            await PlainTextResponse("ok")(scope, receive, send)
            return
        token = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(token, ("Bearer " + KEY).encode()):
            await PlainTextResponse("authentication required", status_code=401)(scope, receive, send)
            return
    await transport(scope, receive, send)
