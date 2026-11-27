import os
from time import perf_counter

import httpx


class LangflowAdapter:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        started = perf_counter()
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=2.0, trust_env=False)
            available = response.status_code == 200
        except httpx.HTTPError:
            available = False
        return {"status": "available" if available else "unavailable",
                "latency_ms": round((perf_counter() - started) * 1000)}


langflow = LangflowAdapter(os.environ.get("LANGFLOW_BASE_URL", "http://langflow:7860"))
