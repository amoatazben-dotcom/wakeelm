from typing import Protocol


class JobHandler(Protocol):
    async def run(self, payload: dict) -> None: ...


class JobQueue:
    """Redis Streams foundation; workers must ack only after successful processing."""

    def __init__(self, redis):
        self.redis = redis

    async def enqueue(self, kind, payload):
        import json

        # Callers must use IDs, never credentials or raw conversation content.
        if set(payload) - {"user_id", "provider_id", "model_id"}:
            raise ValueError("Jobs accept record IDs only")
        return await self.redis.xadd(
            "agent:jobs", {"kind": kind, "payload": json.dumps(payload)}, maxlen=10000
        )
