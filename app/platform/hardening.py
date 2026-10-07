from starlette.exceptions import HTTPException


class RequestBodyLimit:
    def __init__(self, app, max_bytes=2000000):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = 64000 if scope.get("path", "").startswith("/admin") else self.max_bytes
        length = dict(scope.get("headers", [])).get(b"content-length", b"0")
        try:
            invalid = int(length) < 0 or int(length) > limit
        except ValueError:
            invalid = True
        if invalid:
            await send({"type": "http.response.start", "status": 413, "headers": []})
            return await send({"type": "http.response.body", "body": b"Request too large"})
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise HTTPException(413)
            return message

        await self.app(scope, bounded_receive, send)
