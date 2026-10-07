import asyncio
from urllib.parse import unquote, urlsplit, urlunsplit

import aiohttp
import httpx

from app.core.exceptions import SafeError
from app.providers.http import PinnedResolver
from app.providers.url import BaseURLResolver, public_addresses


async def validate_https(url):
    try:
        parts = urlsplit(url)
        base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        normalized = BaseURLResolver.normalize(base)
        if (
            parts.scheme != "https"
            or parts.fragment
            or any(c.isspace() for c in url)
            or "\\" in url
            or any(p in {".", ".."} for p in unquote(parts.path).split("/"))
        ):
            raise ValueError()
        await public_addresses(normalized)
        return url
    except (ValueError, TypeError):
        raise SafeError("INVALID_URL") from None


def origin(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc.lower()}"


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, response, session, limit):
        self.response, self.session, self.limit = response, session, limit

    async def __aiter__(self):
        size = 0
        try:
            async for chunk in self.response.content.iter_chunked(8192):
                size += len(chunk)
                if size > self.limit:
                    raise SafeError("RESPONSE_TOO_LARGE")
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self):
        self.response.close()
        await self.session.close()


class PinnedHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, timeout=30, limit=1000000, allowed_origin=None):
        self.timeout, self.limit, self.allowed_origin = timeout, limit, allowed_origin

    async def handle_async_request(self, request):
        url = str(request.url)
        await validate_https(url)
        if self.allowed_origin and origin(url) != self.allowed_origin:
            raise SafeError("AUTH_ORIGIN_MISMATCH")
        headers = dict(request.headers)
        headers["accept-encoding"] = "identity"
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False),
            timeout=aiohttp.ClientTimeout(
                total=self.timeout, connect=min(5, self.timeout), sock_read=self.timeout
            ),
            trust_env=False,
            auto_decompress=False,
        )
        try:
            response = await session.request(
                request.method,
                url,
                headers=headers,
                data=await request.aread(),
                allow_redirects=False,
            )
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise SafeError("INVALID_RESPONSE")
            if 300 <= response.status < 400:
                raise SafeError("REDIRECT_DENIED")
            return httpx.Response(
                response.status,
                headers=dict(response.headers),
                stream=BoundedStream(response, session, self.limit),
                request=request,
            )
        except BaseException:
            await session.close()
            raise


class IntegrationHTTP:
    runtime_redis = None

    def __init__(self, timeout=30, limit=2000000, transport=None):
        self.timeout, self.limit, self.transport = timeout, limit, transport

    async def request(self, method, url, headers=None, json_body=None, form=None):
        import hashlib

        from app.platform.circuit import CircuitBreaker
        from app.platform.telemetry import TRACE

        key = hashlib.sha256(
            (origin(url) + str(TRACE.get().get("user_id", "system"))).encode()
        ).hexdigest()[:24]
        breaker = (
            CircuitBreaker(self.runtime_redis, "integration:" + key) if self.runtime_redis else None
        )
        if breaker:
            await breaker.before()
        try:
            result = await self._request(method, url, headers, json_body, form)
            if breaker:
                await breaker.success()
            return result
        except SafeError as error:
            if breaker and error.code in {"OFFLINE", "TIMEOUT", "REMOTE_FAILED", "RATE_LIMITED"}:
                await breaker.failure()
            raise

    async def _request(self, method, url, headers=None, json_body=None, form=None):
        from app.platform.telemetry import metric, trace_headers

        headers = {**trace_headers(), **(headers or {})}
        metric("github_calls" if "api.github.com/" in url else "mcp_calls")
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(
                    transport=self.transport or PinnedHTTPTransport(self.timeout, self.limit),
                    follow_redirects=False,
                    trust_env=False,
                    timeout=self.timeout,
                ) as client:
                    response = await client.request(
                        method, url, headers=headers, json=json_body, data=form
                    )
                    if response.status_code >= 300:
                        raise SafeError(
                            {
                                401: "AUTH_FAILED",
                                403: "AUTH_FAILED",
                                404: "NOT_FOUND",
                                429: "RATE_LIMITED",
                            }.get(response.status_code, "REMOTE_FAILED"),
                            response.status_code,
                        )
                    if len(response.content) > self.limit:
                        raise SafeError("RESPONSE_TOO_LARGE")
                    value = response.json()
                    if not isinstance(value, (dict, list)):
                        raise ValueError()
                    return value
        except SafeError:
            raise
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except (httpx.HTTPError, aiohttp.ClientError, OSError):
            raise SafeError("OFFLINE") from None
        except (ValueError, RecursionError):
            raise SafeError("INVALID_RESPONSE") from None
