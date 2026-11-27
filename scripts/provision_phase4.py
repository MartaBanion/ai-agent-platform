"""Install the pinned embedding artifacts and generate internal service credentials."""

import hashlib
import os
import secrets
from pathlib import Path
from urllib.request import urlopen

BASE = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/761b726dd34fb83930e26aab4e9ac3899aa1fa78"
ARTIFACTS = {
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "onnx/model_quantized.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
}


def checksum(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def provision():
    config = Path(".env")
    if config.stat().st_mode & 0o077:
        raise SystemExit(".env must have permissions 0600")
    assignments = dict(line.split("=", 1) for line in config.read_text().splitlines()
                       if "=" in line and not line.startswith("#"))
    with config.open("a") as handle:
        for name in ("PLATFORM_QDRANT_KEY", "PLATFORM_MCP_KEY"):
            if not assignments.get(name):
                handle.write(f"\n{name}={secrets.token_hex(32)}\n")
    directory = Path("data/embedding")
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in ARTIFACTS.items():
        target = directory / Path(name).name
        if target.is_file() and checksum(target) == expected:
            continue
        staging = target.with_suffix(target.suffix + ".partial")
        with urlopen(f"{BASE}/{name}", timeout=60) as response, staging.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 180_000_000:
                    raise SystemExit("Embedding artifact exceeds the size limit")
                output.write(chunk)
        if checksum(staging) != expected:
            raise SystemExit(f"Embedding checksum mismatch: {target.name}")
        os.replace(staging, target)
    print("Internal credentials configured and both embedding checksums verified")


if __name__ == "__main__":
    provision()
