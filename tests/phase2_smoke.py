"""Exercise the deployed loopback portal. Run from the repository root."""

import base64
import http.cookiejar
import json
import re
import secrets
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

settings = dict(
    line.split("=", 1) for line in Path(".env").read_text().splitlines()
    if line and not line.startswith("#") and "=" in line
)
base = "http://127.0.0.1:" + settings.get("PORTAL_PORT", "8080")


class Client:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, status, method="GET", data=None, csrf=True):
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if csrf:
            headers["X-Platform-Request"] = "1"
        request = urllib.request.Request(
            base + path, data=json.dumps(data).encode() if data is not None else None,
            headers=headers, method=method,
        )
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            assert response.status == status, (method, path, response.status, status)
            if body and "application/json" in response.headers.get("Content-Type", ""):
                return json.loads(body), response.headers
            return body, response.headers


def cleanup(user_id, username):
    # Remove only the exact account created by this run. Session rows cascade.
    script = """
from sys import argv
from uuid import UUID
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db import engine
from app.models import User
assert argv[2].startswith("phase2_smoke_")
with Session(engine) as db:
    db.execute(delete(User).where(User.id == UUID(argv[1]), User.username == argv[2]))
    db.commit()
"""
    subprocess.run(["docker", "compose", "exec", "-T", "backend", "python", "-c", script, user_id, username],
                   check=True)


def run():
    admin = Client()
    user = Client()
    anonymous = Client()
    html, headers = anonymous.request("/users", 200)
    assert b'lang="zh-CN"' in html and "frame-ancestors" in headers["Content-Security-Policy"]
    asset_paths = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', html)
    assert asset_paths
    for path in asset_paths:
        asset, _ = anonymous.request(path.decode(), 200)
        for key in ("PLATFORM_DB_PASSWORD", "PLATFORM_JWT_SECRET", "PLATFORM_ADMIN_PASSWORD", "LANGFLOW_SECRET_KEY"):
            assert settings[key].encode() not in asset
    assert anonymous.request("/api/v1/health", 200)[0]["status"] == "healthy"
    for path in ("/auth/me", "/system/overview", "/system/langflow", "/users"):
        anonymous.request("/api/v1" + path, 401)
    assert anonymous.request("/api/v1/auth/login", 403, "POST", {}, csrf=False)[0]["error"]["request_id"]
    anonymous.request("/api/v1/auth/login", 401, "POST", {"username": "unknown_user", "password": "incorrect"})
    print("PASS production SPA, security headers, no embedded credentials, health, anonymous and CSRF rejection")

    username = settings.get("PLATFORM_ADMIN_USERNAME", "portal_admin")
    profile, headers = admin.request("/api/v1/auth/login", 200, "POST",
                                     {"username": username, "password": settings["PLATFORM_ADMIN_PASSWORD"]})
    assert profile["role"] == "admin" and "password_hash" not in profile
    assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=strict" in headers["Set-Cookie"]
    cookie = next(iter(admin.cookies))
    payload = cookie.value.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["sub"] == profile["id"] and claims["exp"] - claims["iat"] == 1800
    assert admin.request("/api/v1/auth/me", 200)[0]["id"] == profile["id"]
    overview, _ = admin.request("/api/v1/system/overview", 200)
    assert overview["users"]["active"] >= 1
    assert overview["services"]["database"] == "available"
    assert overview["services"]["langflow"]["status"] == "available"
    assert admin.request("/api/v1/system/langflow", 200)[0]["status"] == "available"
    print("PASS administrator login, 30-minute HttpOnly JWT, real dashboard and Langflow adapter")

    name = "phase2_smoke_" + secrets.token_hex(6)
    password = secrets.token_hex(16)
    credentials = {"username": name, "password": password}
    create = {**credentials, "role": "user", "display_name": "验收用户"}
    admin.request("/api/v1/users", 422, "POST", {**create, "password": "short"})
    created, _ = admin.request("/api/v1/users", 201, "POST", create)
    user_id = created["id"]
    try:
        path = "/api/v1/users/" + user_id
        admin.request("/api/v1/users", 409, "POST", create)
        listing, _ = admin.request("/api/v1/users?limit=100", 200)
        assert any(item["id"] == user_id for item in listing["items"])
        user.request("/api/v1/auth/login", 200, "POST", credentials)
        user.request("/api/v1/users", 403)
        user.request("/api/v1/users", 403, "POST", create)
        assert user.request("/api/v1/system/overview", 200)[0]["users"] is None
        updated = {"display_name": "验收开发者", "role": "developer", "is_active": True}
        assert admin.request(path, 200, "PUT", updated)[0]["role"] == "developer"
        user.request("/api/v1/auth/me", 401)
        assert user.request("/api/v1/auth/login", 200, "POST", credentials)[0]["role"] == "developer"
        user.request("/api/v1/users", 403)
        new_password = secrets.token_hex(16)
        user.request("/api/v1/auth/password", 204, "POST",
                     {"current_password": password, "new_password": new_password})
        user.request("/api/v1/auth/me", 401)
        credentials["password"] = new_password
        user.request("/api/v1/auth/login", 200, "POST", credentials)
        admin.request(path, 200, "PUT", {**updated, "is_active": False})
        user.request("/api/v1/auth/me", 401)
        user.request("/api/v1/auth/login", 401, "POST", credentials)
        admin.request("/api/v1/auth/logout", 204, "POST")
        admin.cookies.set_cookie(cookie)
        admin.request("/api/v1/auth/me", 401)
        print("PASS validation, duplicate account, create/list/edit, both roles denied, password rotation, disable, logout revocation")
    finally:
        cleanup(user_id, name)

    for _ in range(12):
        try:
            anonymous.request("/api/v1/auth/login", 401, "POST", {"username": "unknown_user", "password": "incorrect"})
        except AssertionError as error:
            if error.args[0][2] != 429:
                raise
            print("PASS login rate limit returns 429")
            break
    else:
        raise AssertionError("Expected login rate limit to return 429")


if __name__ == "__main__":
    run()
