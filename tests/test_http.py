import asyncio

import pytest
from aiohttp import web

from app.core.exceptions import SafeError
from app.providers.http import PinnedResolver, SafeHTTP


@pytest.fixture
async def mock_server(monkeypatch):
    async def allow(url):
        return {"127.0.0.1"}

    async def resolve(self, host, port=0, family=0):
        return [
            {
                "hostname": host,
                "host": "127.0.0.1",
                "port": port,
                "family": 2,
                "proto": 0,
                "flags": 0,
            }
        ]

    monkeypatch.setattr("app.providers.http.public_addresses", allow)
    monkeypatch.setattr(PinnedResolver, "resolve", resolve)

    async def handle(request):
        path = request.path
        if path == "/bad":
            return web.Response(text="not json")
        if path == "/large":
            return web.Response(body=b"x" * 1024)
        if path == "/slow":
            await asyncio.sleep(0.1)
            return web.json_response({"ok": True})
        if path == "/redirect":
            raise web.HTTPFound("http://127.0.0.1/metadata")
        if path.startswith("/status/"):
            return web.Response(
                status=int(path.rsplit("/", 1)[1]), text="secret provider diagnostic"
            )
        return web.json_response({"data": [{"id": "mock-model"}]})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    # Production URL policy restricts ports; this test transport deliberately isolates that policy.
    yield "http://public.test:" + str(port)
    await runner.cleanup()


@pytest.mark.parametrize(
    "path,code",
    [
        ("/bad", "INVALID_RESPONSE"),
        ("/large", "INVALID_RESPONSE"),
        ("/redirect", "OFFLINE"),
        ("/status/401", "AUTH_FAILED"),
        ("/status/403", "AUTH_FAILED"),
        ("/status/429", "RATE_LIMITED"),
        ("/status/404", "UNSUPPORTED"),
        ("/status/503", "OFFLINE"),
    ],
)
async def test_http_errors(mock_server, path, code):
    with pytest.raises(SafeError, match=code) as error:
        await SafeHTTP(max_bytes=100).request(
            "GET", mock_server + path, {"Authorization": "Bearer secret"}
        )
    assert "secret" not in str(error.value)


async def test_http_timeout(mock_server):
    with pytest.raises(SafeError, match="TIMEOUT"):
        await SafeHTTP(timeout=0.01).request("GET", mock_server + "/slow", {})


async def test_http_json(mock_server):
    assert (await SafeHTTP().request("GET", mock_server + "/models", {}))["data"][0][
        "id"
    ] == "mock-model"
