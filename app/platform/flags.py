import hashlib

from app.core.exceptions import SafeError
from app.db.models.platform import FeatureFlag, UserPlan

DEFAULTS = {
    "multi_agent": True,
    "deep_mode": True,
    "experimental_router": True,
    "disable_external_writes": False,
    "disable_github_push": False,
    "disable_mcp_writes": False,
    "disable_new_jobs": False,
    "disable_uploads": False,
    "admin_dashboard_feature": True,
}


class FeatureFlags:
    def __init__(self, session, user_id=None):
        self.session, self.user_id = session, user_id

    async def enabled(self, key):
        row = await self.session.get(FeatureFlag, key, populate_existing=True)
        if row is None:
            return DEFAULTS.get(key, False)
        targets = row.targets_json or {}
        if targets.get("users") and self.user_id not in targets["users"]:
            return False
        if targets.get("plans"):
            plan = await self.session.get(UserPlan, self.user_id)
            if (plan.plan if plan else "FREE") not in targets["plans"]:
                return False
        if "percentage" in targets:
            bucket = int(hashlib.sha256(f"{key}:{self.user_id}".encode()).hexdigest()[:8], 16) % 100
            if bucket >= targets["percentage"]:
                return False
        return row.enabled

    async def require(self, key):
        if not await self.enabled(key):
            raise SafeError("FEATURE_DISABLED")

    async def deny_if(self, key):
        if await self.enabled(key):
            raise SafeError("KILL_SWITCH_ACTIVE")
