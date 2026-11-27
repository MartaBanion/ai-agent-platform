import asyncio
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit

import httpx
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app.provider import UpstreamError, canonical_url, public_destination

LOCAL_VERSION = "multilingual-e5-small@761b726dd34fb83930e26aab4e9ac3899aa1fa78"
MODEL_DIR = Path("/models")
FILES = {
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "model_quantized.onnx": "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
}
slots = BoundedSemaphore(1)


def profile(kind):
    if kind == "local":
        return LOCAL_VERSION, 384
    raw = os.environ.get("EMBEDDING_CLOUD_URL")
    model = os.environ.get("EMBEDDING_CLOUD_MODEL", "").strip()
    key = os.environ.get("EMBEDDING_CLOUD_KEY")
    try:
        if not raw or not model or not key:
            raise ValueError()
        dimension = int(os.environ.get("EMBEDDING_CLOUD_DIMENSION", ""))
        if not 32 <= dimension <= 4096:
            raise ValueError()
        endpoint = canonical_url("custom", raw)
    except ValueError:
        raise UpstreamError("云端 Embedding 尚未配置或配置无效") from None
    signature = hashlib.sha256(f"{endpoint}|{model}|{dimension}".encode()).hexdigest()[:24]
    return f"cloud:{signature}:{model[:100]}", dimension


@lru_cache(maxsize=1)
def runtime():
    try:
        ort.disable_telemetry_events()
        for name, expected in FILES.items():
            with (MODEL_DIR / name).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                    raise ValueError()
        tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(MODEL_DIR / "model_quantized.onnx"), sess_options=options,
                                       providers=["CPUExecutionProvider"])
        return tokenizer, session
    except (OSError, ValueError, RuntimeError, TypeError):
        raise UpstreamError("本地 Embedding 权重缺失或无法加载") from None


def local_vectors(texts, query):
    with slots:
        tokenizer, session = runtime()
        prefix = "query: " if query else "passage: "
        encodings = tokenizer.encode_batch([prefix + value for value in texts])
        masks = np.array([entry.attention_mask for entry in encodings], dtype=np.int64)
        inputs = {"input_ids": np.array([entry.ids for entry in encodings], dtype=np.int64),
                  "attention_mask": masks, "token_type_ids": np.zeros_like(masks)}
        output = session.run(["last_hidden_state"], {field.name: inputs[field.name]
                                                      for field in session.get_inputs()})[0]
        pooled = (output * masks[:, :, None]).sum(axis=1) / masks.sum(axis=1, keepdims=True)
        return normalize(pooled, len(texts), 384)


def normalize(vectors, size, dimension):
    values = np.asarray(vectors, dtype=np.float32)
    if values.shape != (size, dimension) or not np.isfinite(values).all():
        raise UpstreamError("Embedding 返回维度或数值无效")
    lengths = np.linalg.norm(values, axis=1, keepdims=True)
    if (lengths <= 0).any() or not np.isfinite(lengths).all():
        raise UpstreamError("Embedding 返回无效向量")
    return (values / lengths).tolist()


async def cloud_vectors(texts, dimension):
    base = canonical_url("custom", os.environ["EMBEDDING_CLOUD_URL"])
    parts = urlsplit(base)
    host = parts.hostname
    authority = await public_destination(host)
    try:
        async with asyncio.timeout(25):
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                async with client.stream("POST", f"https://{authority}{parts.path}/embeddings",
                                         headers={"Host": host, "Authorization": "Bearer " + os.environ["EMBEDDING_CLOUD_KEY"]},
                                         json={"model": os.environ["EMBEDDING_CLOUD_MODEL"].strip(), "input": texts},
                                         extensions={"sni_hostname": host}) as response:
                    if response.status_code != 200:
                        raise UpstreamError(f"云端 Embedding 返回 HTTP {response.status_code}")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 2_000_000:
                            raise UpstreamError("云端 Embedding 响应过大")
        rows = sorted(json.loads(body)["data"], key=lambda item: item["index"])
        if [row["index"] for row in rows] != list(range(len(texts))):
            raise UpstreamError("云端 Embedding 返回顺序不完整")
        return normalize([row["embedding"] for row in rows], len(texts), dimension)
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
        raise UpstreamError("云端 Embedding 请求失败") from None


def vectors(version, dimension, texts, query=False):
    if version == LOCAL_VERSION and dimension == 384:
        return local_vectors(texts, query)
    if profile("cloud") != (version, dimension):
        raise UpstreamError("知识库的 Embedding 版本与当前配置不符")
    return asyncio.run(cloud_vectors(texts, dimension))
