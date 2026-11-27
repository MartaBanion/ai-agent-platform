import os

import httpx

from app.provider import UpstreamError

BASE = "http://qdrant:6333"


def call(method, path, payload=None, missing=False):
    try:
        with httpx.Client(base_url=BASE, headers={"api-key": os.environ["PLATFORM_QDRANT_KEY"]},
                          timeout=6, trust_env=False) as client:
            response = client.request(method, path, json=payload)
    except httpx.HTTPError:
        raise UpstreamError("向量存储暂不可用") from None
    if missing and response.status_code == 404:
        return None
    if not response.is_success:
        raise UpstreamError(f"向量存储返回 HTTP {response.status_code}")
    return response.json()["result"]


def collection(key):
    return f"/collections/kb_{key.hex}"


def create(key, dimension):
    return call("PUT", collection(key), {"vectors": {"size": dimension, "distance": "Cosine", "on_disk": True},
                                         "on_disk_payload": True})


def remove(key):
    return call("DELETE", collection(key), missing=True)


def erase(key, document):
    return call("POST", collection(key) + "/points/delete?wait=true", {
        "filter": {"must": [{"key": "document", "match": {"value": str(document)}}]},
    })


def write(key, document, revision, rows, vectors):
    return call("PUT", collection(key) + "/points?wait=true", {
        "points": [{"id": str(row.id), "vector": vector,
                    "payload": {"document": str(document), "revision": str(revision)}}
                   for row, vector in zip(rows, vectors, strict=True)],
    })


def search(key, query, revisions, limit, threshold):
    if not revisions:
        return []
    result = call("POST", collection(key) + "/points/query", {
        "query": query, "limit": limit, "score_threshold": threshold, "with_payload": False,
        "filter": {"must": [{"key": "revision", "match": {"any": [str(value) for value in revisions]}}]},
    })
    return result["points"]
