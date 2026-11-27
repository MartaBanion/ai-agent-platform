"""Verify stage-three deployment against real PostgreSQL and Langflow."""

import json
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase2_smoke import Client, cleanup
from seed_ai import admin_login, seed


def events(client, path, request):
    body, headers = client.request("/api/v1" + path, 200, "POST", request)
    assert "text/event-stream" in headers["Content-Type"]
    result = {}
    for frame in body.decode().strip().split("\n\n"):
        event_line, data_line = frame.split("\n", 1)
        event = event_line.removeprefix("event: ")
        result.setdefault(event, []).append(json.loads(data_line.removeprefix("data: ")))
    return result


def text(result):
    assert "done" in result, result.get("error")
    return "".join(item["text"] for item in result.get("delta", []))


def run():
    admin = admin_login()
    normal = Client()
    anonymous = Client()
    tag = secrets.token_hex(5)
    password = secrets.token_hex(16)
    username = "phase2_smoke_phase3_" + tag
    account, _ = admin.request("/api/v1/users", 201, "POST", {
        "username": username, "password": password, "display_name": "第三阶段验收", "role": "user",
    })
    model_id = agent_id = conversation_id = None
    try:
        normal.request("/api/v1/auth/login", 200, "POST", {"username": username, "password": password})
        flows = seed(admin)
        key = flows["echo"]["id"]
        anonymous.request("/api/v1/conversations", 401)
        for path in ("/models", "/workflows", "/workflows/editor"):
            normal.request("/api/v1" + path, 403)
        discovery, _ = admin.request("/api/v1/workflows/discovery", 200)
        assert flows["echo"]["engine_id"] in {item["id"] for item in discovery}
        admin.request(f"/api/v1/workflows/{key}/sync", 200, "POST")
        versions, _ = admin.request(f"/api/v1/workflows/{key}/versions", 200)
        assert versions[0]["number"] >= 1
        exported, _ = admin.request(f"/api/v1/workflows/{key}/export", 200)
        assert {node["data"]["type"] for node in exported["data"]["nodes"]} == {"ChatInput", "ChatOutput"}
        admin.request("/api/v1/workflows", 422, "POST", {
            "name": "Invalid fixture", "kind": "echo", "document": {"data": {"nodes": [], "edges": []}},
        })
        assert text(events(admin, f"/workflows/{key}/run", {"text": "真实 Langflow 文本链路"})) == "真实 Langflow 文本链路"
        history, _ = admin.request(f"/api/v1/workflows/{key}/history", 200)
        assert history[0]["status"] == "success" and history[0]["duration_ms"] >= 0
        assert history[0]["total_tokens"] is None
        print("PASS real Langflow discovery, sync, export, version, SSE execution and measured history")

        existing, _ = admin.request("/api/v1/models", 200)
        should_default = not any(item["is_default"] for item in existing)
        model = {"name": "Smoke " + tag, "provider": "custom", "base_url": "https://localhost.localdomain/v1",
                 "model": "integration-check", "api_key": secrets.token_hex(24), "is_default": should_default, "timeout": 5}
        admin.request("/api/v1/models", 422, "POST", {**model, "base_url": "https://127.0.0.1/v1"})
        normal.request("/api/v1/models", 403, "POST", model)
        response, _ = admin.request("/api/v1/models", 201, "POST", model)
        model_id = response["id"]
        assert response["has_key"] and response["is_default"] == should_default and model["api_key"] not in json.dumps(response)
        admin.request(f"/api/v1/models/{model_id}", 200, "PUT", {**model, "api_key": None})
        admin.request(f"/api/v1/models/{model_id}", 422, "PUT",
                      {**model, "api_key": None, "base_url": "https://example.com/v1"})
        report, _ = admin.request(f"/api/v1/models/{model_id}/test", 502, "POST")
        assert ("域名" in report["error"]["message"]), report["error"]["message"]
        totals, _ = admin.request(f"/api/v1/models/{model_id}/usage", 200)
        assert totals["calls"] == 1 and totals["success"] == 0 and totals["total_tokens"] is None
        options, _ = normal.request("/api/v1/models/options", 200)
        assert not any("base_url" in item or "has_key" in item for item in options)
        ciphertext_test = """
from sys import argv
from uuid import UUID
from sqlalchemy.orm import Session
from app.ai_models import ModelConfig
from app.db import engine
from app.provider import decrypt_key
with Session(engine) as db:
    value = db.get(ModelConfig, UUID(argv[1])).key_ciphertext
    assert value != argv[2] and decrypt_key(value) == argv[2]
"""
        subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c",
                        ciphertext_test, model_id, model["api_key"]], check=True)
        disabled, _ = admin.request(f"/api/v1/models/{model_id}", 200, "PUT",
                                    {**model, "enabled": False, "is_default": False, "api_key": None})
        assert not disabled["enabled"]
        print("PASS model CRUD, default, encryption, credential protection, failed-probe usage and SSRF rejection")

        agent_form = {"name": "联调 " + tag, "workflow_id": key, "icon": "🤖", "published": False}
        agent, _ = admin.request("/api/v1/agents", 201, "POST", agent_form)
        agent_id = agent["id"]
        normal.request(f"/api/v1/agents/{agent_id}", 404)
        normal.request(f"/api/v1/agents/{agent_id}/run", 404, "POST", {"text": "不得访问"})
        admin.request(f"/api/v1/agents/{agent_id}", 200, "PUT", {**agent_form, "published": True})
        public, _ = normal.request(f"/api/v1/agents/{agent_id}", 200)
        assert "system_prompt" not in public
        assert text(events(admin, f"/agents/{agent_id}/run", {"text": "智能体经过实机流程"})) == "智能体经过实机流程"

        conversation, _ = admin.request("/api/v1/conversations", 201, "POST", {})
        conversation_id = conversation["id"]
        link = f"/api/v1/conversations/{conversation_id}"
        normal.request(link + "/messages", 404)
        normal.request(link, 404, "PATCH", {"title": "无权改名"})
        normal.request(link, 404, "DELETE")
        for sample in ("第一轮", "第二轮"):
            result = events(admin, f"/conversations/{conversation_id}/generate", {"agent_id": agent_id, "text": sample})
            assert text(result) == sample
        saved, _ = admin.request(link + "/messages", 200)
        assert [item["content"] for item in saved] == ["第一轮", "第一轮", "第二轮", "第二轮"]
        assert [item["role"] for item in saved] == ["user", "assistant", "user", "assistant"]
        renamed, _ = admin.request(link, 200, "PATCH", {"title": "重命名验收"})
        assert renamed["title"] == "重命名验收"
        admin.request(link, 204, "DELETE")
        conversation_id = None
        print("PASS private/public agent checks, real engine via agent/chat, two-turn history, rename and ownership isolation")
    finally:
        if conversation_id:
            admin.request("/api/v1/conversations/" + conversation_id, 204, "DELETE")
        if agent_id:
            admin.request("/api/v1/agents/" + agent_id, 204, "DELETE")
        if model_id:
            admin.request("/api/v1/models/" + model_id, 204, "DELETE")
        cleanup(account["id"], username)
        admin.request("/api/v1/auth/logout", 204, "POST")


if __name__ == "__main__":
    run()
