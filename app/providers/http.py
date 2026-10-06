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
        await public_addresses(url)  # also blocks numeric literals bypassing resolver
        connector = aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False)
        try:
            async with asyncio.timeout(self.timeout):
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=self.timeout, connect=5, sock_read=15),
                    trust_env=False,
                ) as client:
                    async with client.request(
                        method, url, headers=headers, json=payload, allow_redirects=False
                    ) as response:
                        if response.status >= 300:
                            code = {
                                401: "AUTH_FAILED",
                                403: "AUTH_FAILED",
                                404: "UNSUPPORTED",
                                429: "RATE_LIMITED",
                            }.get(response.status, "OFFLINE")
                            raise SafeError(code, response.status)
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
                        except (ValueError, UnicodeError):
                            raise SafeError("INVALID_RESPONSE") from None
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except aiohttp.ClientError:
            raise SafeError("OFFLINE") from None
