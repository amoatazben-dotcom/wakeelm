from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.base import now
from app.db.models import UserSetting
from app.routing.schemas import RoutingPolicy


class RoutingPreferences:
    def __init__(self, session, user_id):
        self.session, self.user_id = session, user_id

    async def get(self):
        row = await self.session.scalar(
            select(UserSetting).where(
                UserSetting.user_id == self.user_id, UserSetting.key == "routing"
            )
        )
        return (
            row.value_json
            if row
            else {"policy": "MANUAL_ONLY", "fallback_enabled": False, "agent_mode": "BALANCED"}
        )

    async def set(self, policy=None, fallback_enabled=None, agent_mode=None):
        from app.core.exceptions import SafeError

        value = dict(await self.get())
        if policy is not None:
            value["policy"] = RoutingPolicy(policy).value
        if fallback_enabled is not None:
            value["fallback_enabled"] = bool(fallback_enabled)
        if agent_mode is not None:
            if agent_mode not in {"FAST", "BALANCED", "DEEP", "MULTI_AGENT"}:
                raise SafeError("INVALID_INPUT")
            value["agent_mode"] = agent_mode
        insert = pg_insert if self.session.bind.dialect.name == "postgresql" else sqlite_insert
        stmt = insert(UserSetting).values(user_id=self.user_id, key="routing", value_json=value)
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "key"], set_={"value_json": value, "updated_at": now()}
            )
        )
        return value
