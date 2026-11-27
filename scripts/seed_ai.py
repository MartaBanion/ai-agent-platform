"""Register the two supported Langflow templates and the draft IT assistant."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from phase2_smoke import Client, settings


def seed(client):
    flows, _ = client.request("/api/v1/workflows", 200)
    registered = {}
    for kind, name, description in (
        ("echo", "Langflow 文本直通", "用于验证引擎连通和文本输入输出。"),
        ("prompt", "企业 IT 运维对话", "基于 Langflow 内置组件的运维问答工作流。"),
    ):
        flow = next((item for item in flows if item["name"] == name and item["kind"] == kind), None)
        if not flow:
            flow, _ = client.request("/api/v1/workflows", 201, "POST",
                                     {"name": name, "kind": kind, "description": description})
        registered[kind] = flow

    name = "企业 IT 智能运维助手"
    agents, _ = client.request("/api/v1/agents", 200)
    if not any(agent["name"] == name for agent in agents):
        client.request("/api/v1/agents", 201, "POST", {
            "name": name, "description": "协助诊断告警、分析现象并整理安全的排查和恢复步骤。",
            "icon": "🛠️", "workflow_id": registered["prompt"]["id"], "published": False,
            "system_prompt": (
                "你是企业 IT 运维助手。先询问影响范围、系统版本、最近变更及可观测证据。"
                "区分事实和假设，优先给出只读诊断和可回滚建议。"
                "涉及生产变更、删除、凭据、用户数据时，提示人工审批与脱敏。"
                "不要声称已执行命令、查阅日志或确认恢复，除非用户提供了证据。"
            ),
        })
    return registered


def admin_login():
    client = Client()
    client.request("/api/v1/auth/login", 200, "POST", {
        "username": settings.get("PLATFORM_ADMIN_USERNAME", "portal_admin"),
        "password": settings["PLATFORM_ADMIN_PASSWORD"],
    })
    return client


if __name__ == "__main__":
    client = admin_login()
    seed(client)
    client.request("/api/v1/auth/logout", 204, "POST")
    print("Registered Langflow workflows and draft IT assistant")
