"""Exercise the real deployed backend, ONNX and MCP across the portal."""

import io
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from phase2_smoke import Client, base, cleanup
from seed_ai import admin_login


def pdf():
    stream = b"BT /F1 12 Tf 30 40 Td (Office wireless access point installation) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    content = b"%PDF-1.4\n"
    offsets = []
    for number, item in enumerate(objects, 1):
        offsets.append(len(content))
        content += b"%d 0 obj\n%s\nendobj\n" % (number, item)
    count = len(offsets) + 1
    index = b"xref\n0 %d\n0000000000 65535 f \n" % count
    index += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return content + index + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (count, len(content))


def docx():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>采购办公显示器需要财务审批。</w:t></w:r></w:p></w:body></w:document>'
        ))
    return output.getvalue()


def upload(client, path, name, content, expected=202):
    separator = secrets.token_hex(16)
    header = f'--{separator}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n\r\n'
    body = header.encode() + content + f"\r\n--{separator}--\r\n".encode()
    request = urllib.request.Request(base + path, data=body, headers={
        "Content-Type": "multipart/form-data; boundary=" + separator, "X-Platform-Request": "1",
    })
    try:
        response = client.opener.open(request, timeout=18)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (name, response.status, expected)
        return json.load(response)


def ready(admin, path, identifiers):
    for _ in range(45):
        rows, _ = admin.request(path + "/documents", 200)
        statuses = {row["id"]: row for row in rows if row["id"] in identifiers}
        assert not any(row["status"] == "failed" for row in statuses.values()), statuses
        if len(statuses) == len(identifiers) and all(row["status"] == "ready" for row in statuses.values()):
            return
        time.sleep(1)
    raise AssertionError("Document processing did not finish")


def vector_count(key):
    code = """
import os,sys,httpx
base='http://qdrant:6333'
assert httpx.get(base+'/collections').status_code in (401,403)
result=httpx.post(base+'/collections/kb_'+sys.argv[1].replace('-','')+'/points/count',
                 headers={'api-key':os.environ['PLATFORM_QDRANT_KEY']},json={'exact':True})
result.raise_for_status()
print(result.json()['result']['count'])
"""
    return int(subprocess.check_output(["docker", "compose", "exec", "-T", "backend", "python", "-c", code, key]))


def remove_account(identifier, username):
    code = """
from sys import argv
from uuid import UUID
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.knowledge_models import ToolCall
from app.db import engine
with Session(engine) as session:
    session.execute(delete(ToolCall).where(ToolCall.owner_id == UUID(argv[1])))
    session.commit()
"""
    assert username.startswith("phase2_smoke_phase4_")
    subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c", code, identifier], check=True)
    cleanup(identifier, username)


def run(restart_qdrant=False):
    admin, normal = admin_login(), Client()
    tag = secrets.token_hex(4)
    username, password = "phase2_smoke_phase4_" + tag, secrets.token_hex(16)
    account, _ = admin.request("/api/v1/users", 201, "POST", {
        "username": username, "display_name": "第四阶段验收", "role": "user", "password": password,
    })
    key = server_id = agent_id = None
    path = "/api/v1/knowledge"
    tool_path = "/api/v1/mcp/servers"
    try:
        normal.request("/api/v1/auth/login", 200, "POST", {"username": username, "password": password})
        form = {"name": "第四阶段语义检索 " + tag, "embedding": "local", "threshold": 0.30}
        kb, _ = admin.request(path, 201, "POST", form)
        key = kb["id"]
        endpoint = path + "/" + key
        assert kb["dimension"] == 384 and "multilingual-e5-small@" in kb["profile"]
        normal.request(endpoint + "/documents", 404)
        normal.request(path, 403, "POST", form)
        upload(admin, endpoint + "/documents", "malformed.pdf", b"Bad file data", 422)
        fixtures = {
            "credentials.md": "身份认证：当员工无法记起账号的密码，可通过身份核验，在统一认证页面进行凭证重置。等待邮件发送确认链接。".encode(),
            "printer.txt": "打印机卡纸时先关闭电源，取出硒鼓和被卡住的纸张，再检查送纸辊是否有残留纸片。".encode(),
            "wireless.pdf": pdf(),
            "purchasing.docx": docx(),
        }
        docs = {name: upload(admin, endpoint + "/documents", name, content)["id"]
                for name, content in fixtures.items()}
        ready(admin, endpoint, set(docs.values()))
        query = {"text": "我忘了登录口令，怎么找回访问权限？", "top_k": 4, "threshold": 0.0}
        hits, _ = admin.request(endpoint + "/search", 200, "POST", query)
        assert hits[0]["document"] == "credentials.md" and hits[0]["score"] > hits[-1]["score"], hits
        print("Real semantic ordering:", [(item["document"], round(item["score"], 3)) for item in hits])
        assert admin.request(hits[0]["download_url"], 200)[0] == fixtures["credentials.md"]
        pages, _ = admin.request(endpoint + f"/documents/{docs['wireless.pdf']}/passages", 200)
        assert pages[0]["page"] == 1 and "wireless access" in pages[0]["text"]
        assert vector_count(key) == 4
        if restart_qdrant:
            subprocess.run(["docker", "compose", "restart", "qdrant"], check=True)
            subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "--wait", "qdrant"], check=True)
            hits, _ = admin.request(endpoint + "/search", 200, "POST", query)
            assert hits[0]["document"] == "credentials.md" and vector_count(key) == 4
        credential_link = endpoint + f"/documents/{docs['credentials.md']}"
        admin.request(credential_link + "/reprocess", 202, "POST")
        ready(admin, endpoint, {docs["credentials.md"]})
        assert vector_count(key) == 4
        print("PASS PDF, DOCX, TXT, Markdown, real Embedding, download, page citation, Qdrant auth and reprocess")

        server, _ = admin.request(tool_path, 201, "POST", {"name": "临时运维工具 " + tag, "kind": "builtin", "shared": True})
        server_id = server["id"]
        tools = tool_path + "/" + server_id
        result, _ = admin.request(tools + "/test", 200, "POST")
        assert len(result["tools"]) == 6
        normal.request(tools + "/calls", 404, "POST", {"tool": "current_time"})
        allow = {"name": server["name"], "kind": "builtin", "shared": True,
                 "allowed": ["current_time", "network_calculation", "connectivity_check", "resource_metrics"]}
        admin.request(tools, 200, "PUT", allow)
        normal.request(tools, 403, "PUT", allow)
        normal.request(tools + "/calls", 422, "POST", {
            "tool": "connectivity_check", "arguments": {"target": "outside_allowlist"},
        })
        flows, _ = admin.request("/api/v1/workflows", 200)
        flow = next(row for row in flows if row["kind"] == "echo")
        agent, _ = admin.request("/api/v1/agents", 201, "POST", {
            "name": "第四阶段测试智能体 " + tag, "workflow_id": flow["id"], "published": True,
        })
        agent_id = agent["id"]
        agent_base = "/api/v1/agents/" + agent_id
        normal.request(agent_base + "/resources", 403)
        normal.request(tools + "/calls", 403, "POST", {"tool": "network_calculation", "agent_id": agent_id})
        admin.request(agent_base + "/resources", 200, "PUT", {
            "knowledge_ids": [key], "tools": [{"server_id": server_id, "name": "network_calculation"}],
        })
        assert normal.request(agent_base + "/knowledge-context", 200, "POST", query)[0] == []
        form.pop("embedding")
        admin.request(endpoint, 200, "PUT", {**form, "shared": True})
        assert normal.request(agent_base + "/knowledge-context", 200, "POST", query)[0][0]["document"] == "credentials.md"
        normal.request(credential_link, 403, "DELETE")
        admin.request(endpoint, 200, "PUT", {**form, "enabled": False})
        admin.request(endpoint + "/search", 409, "POST", query)
        admin.request(endpoint, 200, "PUT", {**form, "enabled": True})

        request = {"tool": "network_calculation", "arguments": {"cidr": "192.0.2.53/26"}, "agent_id": agent_id}
        row, _ = normal.request(tools + "/calls", 201, "POST", request)
        assert row["state"] == "pending" and row["result"] is None
        review = f"/api/v1/mcp/calls/{row['id']}/review"
        normal.request(review, 403, "POST", {"approve": True})
        row, _ = admin.request(review, 200, "POST", {"approve": True})
        assert row["state"] == "success" and row["result"]["structured"]["network"] == "192.0.2.0/26"
        assert row["duration_ms"] >= 0 and row["arguments"] is None
        admin.request(review, 409, "POST", {"approve": True})
        row, _ = normal.request(tools + "/calls", 201, "POST", {"tool": "network_calculation", "arguments": {"cidr": "invalid"}})
        row, _ = admin.request(f"/api/v1/mcp/calls/{row['id']}/review", 200, "POST", {"approve": True})
        assert row["state"] == "failed" and row["error"]
        row, _ = normal.request(tools + "/calls", 201, "POST", {"tool": "current_time"})
        row, _ = admin.request(f"/api/v1/mcp/calls/{row['id']}/review", 200, "POST", {"approve": False})
        assert row["state"] == "rejected" and row["result"] is None
        admin.request(tool_path, 422, "POST", {"name": "private", "kind": "external", "url": "https://127.0.0.1/mcp"})
        print("PASS real MCP discovery, tool call, schema validation, approval/rejection, failure log and agent grant")
        admin.request(credential_link, 204, "DELETE")
        assert vector_count(key) == 3
        remaining, _ = admin.request(endpoint + "/search", 200, "POST", query)
        assert all(row["document_id"] != docs["credentials.md"] for row in remaining)
        print("PASS document deletion removes points and citations; private/shared KB isolation and RAG context")
    finally:
        if agent_id:
            admin.request("/api/v1/agents/" + agent_id, 204, "DELETE")
        if server_id:
            admin.request(tool_path + "/" + server_id, 204, "DELETE")
        if key:
            admin.request(path + "/" + key, 204, "DELETE")
        remove_account(account["id"], username)
        admin.request("/api/v1/auth/logout", 204, "POST")


if __name__ == "__main__":
    run("--restart-qdrant" in sys.argv)
