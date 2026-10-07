import uuid
from decimal import Decimal

from sqlalchemy import and_, case, func, select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models import User
from app.db.models.agent import AgentJob
from app.db.models.platform import PlanPolicy, UsageEntry, UserPlan
from app.db.models.projects import Workspace

DEFAULT_LIMITS = {
    "FREE": {
        "messages_day": 50,
        "tokens_day": 100000,
        "jobs_day": 10,
        "concurrent_jobs": 2,
        "storage_bytes": 100000000,
        "repositories": 3,
        "mcp_connections": 3,
        "github_repositories": 5,
        "monthly_spend": 5,
        "daily_spend": 1,
        "max_upload_bytes": 20000000,
    },
    "STANDARD": {
        "messages_day": 500,
        "tokens_day": 1000000,
        "jobs_day": 100,
        "concurrent_jobs": 5,
        "storage_bytes": 1000000000,
        "repositories": 20,
        "mcp_connections": 20,
        "github_repositories": 50,
        "monthly_spend": 50,
        "daily_spend": 10,
        "max_upload_bytes": 20000000,
    },
    "PRO": {
        "messages_day": 2000,
        "tokens_day": 5000000,
        "jobs_day": 500,
        "concurrent_jobs": 10,
        "storage_bytes": 5000000000,
        "repositories": 100,
        "mcp_connections": 100,
        "github_repositories": 200,
        "monthly_spend": 200,
        "daily_spend": 50,
        "max_upload_bytes": 50000000,
    },
}
DEFAULT_LIMITS["ADMIN"] = dict(DEFAULT_LIMITS["PRO"])


class QuotaEngine:
    def __init__(self, session, user_id, settings=None):
        self.session, self.user_id, self.settings = session, user_id, settings

    async def limits(self):
        assignment = await self.session.get(UserPlan, self.user_id)
        name = assignment.plan if assignment else "FREE"
        policy = await self.session.get(PlanPolicy, name)
        limits = dict(
            policy.limits_json if policy else DEFAULT_LIMITS.get(name, DEFAULT_LIMITS["FREE"])
        )
        if assignment:
            limits.update(assignment.overrides_json)
        return limits

    async def lock(self):
        user = await self.session.scalar(
            select(User)
            .where(User.id == self.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not user or not user.is_active:
            raise SafeError("INACTIVE")

    async def reserve(
        self,
        operation,
        input_tokens=0,
        output_tokens=0,
        cost=None,
        provider_id=None,
        model_id=None,
        job_id=None,
        key=None,
    ):
        if self.session.bind.dialect.name == "postgresql":
            from sqlalchemy import text

            await self.session.execute(text("SELECT pg_advisory_xact_lock(78124801)"))
        await self.lock()
        limits = await self.limits()
        day = now().replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        today, monthly = await self.totals(day), await self.totals(month)
        tokens = today["tokens"]
        if operation == "model" and self.settings:
            global_total = await self.session.scalar(
                select(func.coalesce(func.sum(UsageEntry.estimated_cost), 0)).where(
                    UsageEntry.created_at >= day, UsageEntry.status != "REJECTED"
                )
            )
            provider_total = await self.session.scalar(
                select(func.coalesce(func.sum(UsageEntry.estimated_cost), 0)).where(
                    UsageEntry.created_at >= day,
                    UsageEntry.status != "REJECTED",
                    UsageEntry.provider_id == provider_id,
                )
            )
            expected = Decimal(str(cost)) if cost is not None else Decimal("0.10")
            if global_total + expected > Decimal(
                str(getattr(self.settings, "global_daily_cost_cap", 100))
            ) or provider_total + expected > Decimal(
                str(getattr(self.settings, "provider_daily_cost_cap", 50))
            ):
                raise SafeError("QUOTA_EXCEEDED")
        reserved_cost = Decimal(str(cost)) if cost is not None else Decimal("0.10")
        if operation == "model" and (
            tokens + input_tokens + output_tokens > limits["tokens_day"]
            or Decimal(monthly["estimated_cost"]) + reserved_cost
            > Decimal(str(limits["monthly_spend"]))
            or Decimal(today["estimated_cost"]) + reserved_cost
            > Decimal(str(limits["daily_spend"]))
        ):
            raise SafeError("QUOTA_EXCEEDED")
        if operation == "message" and today["messages"] >= limits["messages_day"]:
            raise SafeError("QUOTA_EXCEEDED")
        if operation == "job":
            active = await self.session.scalar(
                select(func.count())
                .select_from(AgentJob)
                .where(
                    AgentJob.user_id == self.user_id,
                    AgentJob.status.in_(
                        [
                            "QUEUED",
                            "PLANNING",
                            "RUNNING",
                            "WAITING_APPROVAL",
                            "RECOVERING",
                            "CANCEL_REQUESTED",
                        ]
                    ),
                )
            )
            if active >= limits["concurrent_jobs"] or today["jobs"] >= limits["jobs_day"]:
                raise SafeError("QUOTA_EXCEEDED")
        # SQL reservations survive crashes and are counted conservatively until reconciliation.
        row = UsageEntry(
            idempotency_key=key or uuid.uuid4().hex,
            user_id=self.user_id,
            provider_id=provider_id,
            model_id=model_id,
            job_id=job_id,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pricing_status="KNOWN" if cost is not None else "UNKNOWN",
            estimated_cost=reserved_cost if operation == "model" else Decimal(0),
            status="RESERVED",
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def resource(self, kind, additional=1):
        await self.lock()
        limits = await self.limits()
        if kind == "storage_bytes":
            used = await self.session.scalar(
                select(func.coalesce(func.sum(Workspace.size_bytes), 0)).where(
                    Workspace.user_id == self.user_id, Workspace.status != "DELETED"
                )
            )
        elif kind == "repositories":
            used = await self.session.scalar(
                select(func.count())
                .select_from(Workspace)
                .where(
                    Workspace.user_id == self.user_id,
                    Workspace.type == "REPOSITORY",
                    Workspace.status != "DELETED",
                )
            )
        elif kind == "mcp_connections":
            from app.db.models.integrations import MCPServer

            used = await self.session.scalar(
                select(func.count()).select_from(MCPServer).where(MCPServer.user_id == self.user_id)
            )
        elif kind == "github_repositories":
            from app.db.models.integrations import GitHubConnection, GitHubRepository

            used = await self.session.scalar(
                select(func.count())
                .select_from(GitHubRepository)
                .join(GitHubConnection)
                .where(GitHubConnection.user_id == self.user_id)
            )
        else:
            raise SafeError("INVALID_INPUT")
        if (used or 0) + additional > limits[kind]:
            raise SafeError("QUOTA_EXCEEDED")

    async def totals(self, since):
        values = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(case((UsageEntry.operation == "model", 1), else_=0)), 0),
                    func.coalesce(func.sum(UsageEntry.input_tokens + UsageEntry.output_tokens), 0),
                    func.coalesce(func.sum(case((UsageEntry.operation == "job", 1), else_=0)), 0),
                    func.coalesce(
                        func.sum(case((UsageEntry.operation == "message", 1), else_=0)), 0
                    ),
                    func.coalesce(func.sum(UsageEntry.estimated_cost), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        UsageEntry.pricing_status == "UNKNOWN",
                                        UsageEntry.operation == "model",
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    UsageEntry.user_id == self.user_id,
                    UsageEntry.created_at >= since,
                    UsageEntry.status != "REJECTED",
                )
            )
        ).one()
        return {
            "requests": values[0],
            "tokens": values[1],
            "jobs": values[2],
            "messages": values[3],
            "estimated_cost": str(values[4]),
            "unknown_price_requests": values[5],
        }

    async def summary(self):
        day = now().replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "today": await self.totals(day),
            "month": await self.totals(day.replace(day=1)),
            "limits": await self.limits(),
        }
