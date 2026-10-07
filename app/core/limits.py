import uuid
from contextlib import asynccontextmanager

from app.core.exceptions import SafeError


class Limits:
    def __init__(self, redis):
        self.redis = redis

    async def cooldown(self, key, seconds):
        if not await self.redis.set("limit:" + key, "1", nx=True, px=max(1, int(seconds * 1000))):
            raise SafeError("RATE_LIMITED")

    @asynccontextmanager
    async def lock(self, key, seconds=60):
        token = uuid.uuid4().hex
        key = "lock:" + key
        if not await self.redis.set(key, token, nx=True, ex=seconds):
            raise SafeError("RATE_LIMITED")
        try:
            yield
        finally:
            await self.redis.eval(
                "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
