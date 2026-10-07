from app.core.exceptions import SafeError


class CircuitBreaker:
    """Redis shared circuit. Only the lease winner probes a HALF_OPEN circuit."""

    def __init__(self, redis, key, threshold=3, cooldown=30):
        self.redis, self.key = redis, "circuit:" + key
        self.threshold, self.cooldown = threshold, cooldown
        self.probe = False

    async def before(self):
        state = await self.redis.get(self.key + ":open")
        if state:
            raise SafeError("PROVIDER_OFFLINE")
        failures = int(await self.redis.get(self.key + ":failures") or 0)
        if failures >= self.threshold:
            self.probe = bool(await self.redis.set(self.key + ":probe", "1", nx=True, ex=60))
            if not self.probe:
                raise SafeError("PROVIDER_OFFLINE")

    async def success(self):
        await self.redis.delete(self.key + ":failures", self.key + ":open", self.key + ":probe")

    async def failure(self):
        failures = await self.redis.incr(self.key + ":failures")
        await self.redis.expire(self.key + ":failures", self.cooldown * 10)
        if failures >= self.threshold:
            await self.redis.set(self.key + ":open", "1", ex=self.cooldown)
        if self.probe:
            await self.redis.delete(self.key + ":probe")
