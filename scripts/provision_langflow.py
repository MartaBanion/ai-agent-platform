"""Provision the local Langflow API identity without printing credentials."""

import base64
import json
import os
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PATH = ".env"
if os.stat(PATH).st_mode & 0o077:
    raise SystemExit(".env must have permissions 0600")


def save(name, value):
    with open(PATH, "a") as env_file:
        env_file.write(f"\n{name}={value}\n")
    env[name] = value


with open(PATH) as env_file:
    env = dict(line.strip().split("=", 1) for line in env_file if "=" in line and not line.startswith("#"))

base = "http://127.0.0.1:" + env.get("LANGFLOW_PORT", "7860") + "/api/v1"


def request(path, body=None, token=None, method=None, form=False):
    headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if body is None else (urlencode(body) if form else json.dumps(body)).encode()
    try:
        with urlopen(Request(base + path, data=data, headers=headers, method=method), timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        raise SystemExit(f"Langflow {method or 'request'} {path.split('?')[0]} returned HTTP {error.code}") from None


def login(username, password):
    return request("/login", {"username": username, "password": password}, form=True)["access_token"]


def main():
    if not env.get("PLATFORM_MODEL_KEY"):
        save("PLATFORM_MODEL_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    try:
        session = login("platform_flow_service", env["PLATFORM_LANGFLOW_SERVICE_PASSWORD"])
    except (SystemExit, KeyError):
        name = "platform_flow_service"
        if not env.get("PLATFORM_LANGFLOW_SERVICE_PASSWORD"):
            save("PLATFORM_LANGFLOW_SERVICE_PASSWORD", secrets.token_hex(32))
        admin = login(env.get("LANGFLOW_SUPERUSER", "platform_admin"), env["LANGFLOW_SUPERUSER_PASSWORD"])
        found = request("/users/?" + urlencode({"username": name}), token=admin)
        rows = found if isinstance(found, list) else found.get("users", found.get("items", []))
        user = next((row for row in rows if row["username"] == name), None)
        if not user:
            user = request("/users/", {"username": name, "password": env["PLATFORM_LANGFLOW_SERVICE_PASSWORD"]},
                           token=admin)
        if user.get("is_superuser"):
            raise SystemExit("The integration identity must be non-admin")
        if not user.get("is_active"):
            request("/users/" + user["id"], {"is_active": True}, token=admin, method="PATCH")
        session = login(name, env["PLATFORM_LANGFLOW_SERVICE_PASSWORD"])
    flows = request("/flows/?header_flows=true&page=1&size=20", token=session)
    examples = request("/flows/basic_examples/", token=session)
    print("Langflow service authentication verified; available starter examples:", len(examples))
    print("Native flow discovery shape:", "list" if isinstance(flows, list) else ",".join(flows))


if __name__ == "__main__":
    main()
