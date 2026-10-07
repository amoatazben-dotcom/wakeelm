import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import aiohttp
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core.exceptions import SafeError
from app.integrations.http import PinnedHTTPTransport, origin, validate_https


def safe_mcp_error(error):
    if isinstance(error, SafeError):
        return error
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401:
        return SafeError("AUTH_REQUIRED")
    if isinstance(error, (httpx.TransportError, aiohttp.ClientError, OSError)):
        return SafeError("OFFLINE")
    for child in getattr(error, "exceptions", []):
        value = safe_mcp_error(child)
        if value.code != "MCP_FAILED":
            return value
    return SafeError("MCP_FAILED")


class MCPClient:
    def __init__(self, settings, transport_factory=None):
        self.settings, self.transport_factory = settings, transport_factory

    @asynccontextmanager
    async def session(self, url, token=None):
        await validate_https(url)
        transport = (
            self.transport_factory(url)
            if self.transport_factory
            else PinnedHTTPTransport(
                self.settings.mcp_call_timeout_seconds,
                self.settings.mcp_max_response_bytes,
                origin(url),
            )
        )
        headers = {"Authorization": "Bearer " + token} if token else {}
        try:
            async with asyncio.timeout(self.settings.mcp_call_timeout_seconds):
                async with httpx.AsyncClient(
                    transport=transport,
                    headers=headers,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=self.settings.mcp_connect_timeout_seconds,
                ) as client:
                    async with streamable_http_client(url, http_client=client) as (read, write, _):
                        async with ClientSession(
                            read,
                            write,
                            read_timeout_seconds=timedelta(
                                seconds=self.settings.mcp_call_timeout_seconds
                            ),
                        ) as session:
                            initialized = await session.initialize()
                            yield session, initialized
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except Exception as error:
            raise safe_mcp_error(error) from None

    async def discover(self, url, token=None):
        async with self.session(url, token) as (session, initialized):

            async def collect(method, key):
                rows = []
                cursor = None
                seen = set()
                for _ in range(10):
                    result = await method(cursor=cursor)
                    rows.extend(getattr(result, key))
                    if len(rows) > self.settings.mcp_max_capabilities:
                        raise SafeError("TOO_MANY_CAPABILITIES")
                    cursor = result.nextCursor
                    if not cursor:
                        return [r.model_dump(mode="json", by_alias=True) for r in rows]
                    if cursor in seen:
                        raise SafeError("INVALID_RESPONSE")
                    seen.add(cursor)
                raise SafeError("TOO_MANY_CAPABILITIES")

            caps = initialized.capabilities
            tools = await collect(session.list_tools, "tools") if caps.tools else []
            resources = await collect(session.list_resources, "resources") if caps.resources else []
            templates = (
                await collect(session.list_resource_templates, "resourceTemplates")
                if caps.resources
                else []
            )
            prompts = await collect(session.list_prompts, "prompts") if caps.prompts else []
            return {
                "protocol_version": initialized.protocolVersion,
                "server_info": initialized.serverInfo.model_dump(mode="json"),
                "capabilities": caps.model_dump(mode="json"),
                "tools": tools,
                "resources": resources,
                "resource_templates": templates,
                "prompts": prompts,
            }

    async def call(self, url, name, arguments, token=None):
        async with self.session(url, token) as (session, _):
            result = await session.call_tool(name, arguments)
            if result.isError:
                raise SafeError("EXTERNAL_TOOL_FAILED")
            return result.model_dump(mode="json", by_alias=True)

    async def read_resource(self, url, uri, token=None):
        async with self.session(url, token) as (session, _):
            return (await session.read_resource(uri)).model_dump(mode="json", by_alias=True)

    async def get_prompt(self, url, name, arguments, token=None):
        async with self.session(url, token) as (session, _):
            return (await session.get_prompt(name, arguments)).model_dump(
                mode="json", by_alias=True
            )
