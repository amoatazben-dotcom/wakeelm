import asyncio
import json
import socket

import aiohttp
from aiohttp.abc import AbstractResolver

from app.core.exceptions import SafeError
from app.providers.url import public_addresses


class PinnedResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await public_addresses("https://" + host)
        return [
            {
                "hostname": host,
                "host": ip,
                "port": port,
                "family": socket.AF_INET6 if ":" in ip else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for ip in addresses
        ]

    async def close(self):
        pass


class SafeHTTP:
    def __init__(self, timeout=30, max_bytes=2_000_000):
        self.timeout, self.max_bytes = timeout, max_bytes

    async def request(self, method, url, headers, payload=None):
        from app.platform.telemetry import trace_headers

        headers = {**trace_headers(), **headers}
        await public_addresses(url)  # also blocks numeric literals bypassing resolver
        connector = aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False)
        try:
            async with asyncio.timeout(self.timeout):
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=self.timeout, connect=5, sock_read=15),
                    trust_env=False,
                    auto_decompress=False,
                ) as client:
                    async with client.request(
                        method,
                        url,
                        headers={"Accept-Encoding": "identity", **headers},
                        json=payload,
                        allow_redirects=False,
                    ) as response:
                        if response.status >= 300:
                            code = {
                                401: "AUTH_FAILED",
                                403: "AUTH_FAILED",
                                404: "UNSUPPORTED",
                                429: "RATE_LIMITED",
                            }.get(response.status, "OFFLINE")
                            raise SafeError(code, response.status)
                        if (
                            response.headers.get("Content-Encoding", "identity").lower()
                            != "identity"
                        ):
                            raise SafeError("INVALID_RESPONSE")
                        content = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            content.extend(chunk)
                            if len(content) > self.max_bytes:
                                raise SafeError("INVALID_RESPONSE")
                        try:
                            result = json.loads(content)
                            if not isinstance(result, dict):
                                raise ValueError()
                            return result
                        except (ValueError, UnicodeError, RecursionError):
                            raise SafeError("INVALID_RESPONSE") from None
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except aiohttp.ClientError:
            raise SafeError("OFFLINE") from None

    async def stream(self, url, headers, payload):
        """Bounded SSE transport using the same pinned public DNS as JSON requests."""
        await public_addresses(url)
        connector = aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False)
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                trust_env=False,
                auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=180, connect=5, sock_read=30),
                read_bufsize=65536,
            ) as client:
                async with client.post(
                    url,
                    headers={"Accept-Encoding": "identity", **headers},
                    json=payload,
                    allow_redirects=False,
                ) as response:
                    if response.status >= 300:
                        raise SafeError(
                            {
                                401: "AUTH_FAILED",
                                403: "AUTH_FAILED",
                                404: "UNSUPPORTED",
                                429: "RATE_LIMITED",
                            }.get(response.status, "OFFLINE"),
                            response.status,
                        )
                    if response.headers.get(
                        "Content-Encoding", "identity"
                    ) != "identity" or not response.headers.get("Content-Type", "").startswith(
                        "text/event-stream"
                    ):
                        raise SafeError("INVALID_RESPONSE")
                    size, data = 0, []
                    async for line in response.content:
                        size += len(line)
                        if size > self.max_bytes or len(line) > 65536:
                            raise SafeError("INVALID_RESPONSE")
                        try:
                            line = line.decode("utf-8").rstrip("\r\n")
                        except UnicodeError:
                            raise SafeError("INVALID_RESPONSE") from None
                        if not line and data:
                            value = "\n".join(data)
                            data.clear()
                            if value == "[DONE]":
                                return
                            try:
                                item = json.loads(value)
                                if not isinstance(item, dict):
                                    raise ValueError()
                            except (ValueError, RecursionError):
                                raise SafeError("INVALID_RESPONSE") from None
                            yield item
                        elif line.startswith("data:"):
                            data.append(line[5:].lstrip(" "))
                    # A missing DONE sentinel is a truncated generation, never success.
                    raise SafeError("INVALID_RESPONSE")
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except (aiohttp.ClientError, ValueError):
            raise SafeError("OFFLINE") from None
