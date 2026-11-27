"""Unit checks for provider validation, token accounting and stream cancellation."""

import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

from app.execution import Stopped, next_event, pump
from app.flow_runtime import native_text, native_usage
from app.provider import UpstreamError, canonical_url, pinned_url, public_ip, usage_from


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_restricted_urls_and_addresses(self):
        for endpoint in ("http://example.com/v1", "https://127.0.0.1/v1", "https://a:b@example.com/v1",
                         "https://example.com:8443/v1", "https://example.com/v1?k=token"):
            with self.assertRaises(ValueError):
                canonical_url("custom", endpoint)
        for ip in ("127.0.0.1", "10.0.0.8", "100.64.0.10", "169.254.169.254", "224.0.0.1",
                   "::1", "fd00::1", "fec0::1", "64:ff9b::a00:1", "::ffff:127.0.0.1"):
            self.assertFalse(public_ip(ip), ip)

    async def test_dns_pinning_and_mixed_addresses(self):
        loop = asyncio.get_running_loop()
        endpoint = "https://models.example.com/v1"
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.10.10.10", 443))
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=[public, private])):
            with self.assertRaises(UpstreamError):
                await pinned_url(endpoint)
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=[public])):
            self.assertEqual(await pinned_url(endpoint), ("https://1.1.1.1/v1/chat/completions", "models.example.com"))

    def test_usage_remains_unknown(self):
        self.assertEqual(usage_from({}), {})
        self.assertEqual(usage_from({"usage": {"prompt_tokens": 4, "total_tokens": None}}), {"input_tokens": 4})
        self.assertEqual(native_usage({"outputs": [{"outputs": [{"token_usage": None}]}]}), {})
        self.assertEqual(native_text({"outputs": [{"outputs": [
            {"results": {"message": {"data": {"text": "engine output"}}}},
        ]}]}), "engine output")


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_releases_the_generator(self):
        closed = asyncio.Event()

        async def events():
            try:
                yield "delta", "first"
                await asyncio.sleep(30)
            finally:
                closed.set()

        signal = asyncio.Event()
        queue = asyncio.Queue()
        producer = asyncio.create_task(pump(events(), queue))
        self.assertEqual(await next_event(queue, signal), ("delta", "first"))
        signal.set()
        with self.assertRaises(Stopped):
            await next_event(queue, signal)
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
