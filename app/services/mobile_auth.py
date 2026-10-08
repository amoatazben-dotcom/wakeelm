"""Opaque, hashed, single-use Telegram pairing and rotating mobile sessions."""

import hashlib
import json
import secrets

from fastapi import HTTPException


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class MobileAuth:
    ACCESS_TTL = 900
    REFRESH_TTL = 2592000

    def __init__(self, redis):
        self.redis = redis

    async def pair(self, user_id):
        code = secrets.token_urlsafe(24)
        await self.redis.set("mobile:pair:" + digest(code), user_id, ex=300)
        return code

    async def issue(self, user_id, family=None):
        new_family = family is None
        family = family or secrets.token_hex(32)
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        record = json.dumps({"user_id": user_id, "family": family})
        pipe = self.redis.pipeline(transaction=True)
        if new_family:
            pipe.set("mobile:family:" + family, user_id, ex=self.REFRESH_TTL)
        pipe.set("mobile:access:" + digest(access), record, ex=self.ACCESS_TTL)
        pipe.set("mobile:refresh:" + digest(refresh), record, ex=self.REFRESH_TTL)
        # Retain lineage for reuse detection after refresh rotation.
        pipe.set("mobile:lineage:" + digest(refresh), family, ex=self.REFRESH_TTL)
        await pipe.execute()
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.ACCESS_TTL}

    async def exchange(self, code):
        value = await self.redis.getdel("mobile:pair:" + digest(code))
        if not value:
            raise HTTPException(401, "AUTH_REQUIRED")
        return await self.issue(int(value))

    async def refresh(self, token):
        value = await self.redis.getdel("mobile:refresh:" + digest(token))
        if not value:
            family = await self.redis.get("mobile:lineage:" + digest(token))
            if family:
                await self.redis.delete("mobile:family:" + family.decode())
            raise HTTPException(401, "AUTH_REQUIRED")
        record = json.loads(value)
        if not await self.redis.exists("mobile:family:" + record["family"]):
            raise HTTPException(401, "AUTH_REQUIRED")
        return await self.issue(record["user_id"], record["family"])

    async def verify(self, token):
        value = await self.redis.get("mobile:access:" + digest(token))
        if not value:
            raise HTTPException(401, "AUTH_REQUIRED")
        record = json.loads(value)
        if not await self.redis.exists("mobile:family:" + record["family"]):
            raise HTTPException(401, "AUTH_REQUIRED")
        return record

    async def logout(self, token):
        record = await self.verify(token)
        await self.redis.delete("mobile:family:" + record["family"])
