from app.core.exceptions import SafeError


class ToolPolicyEngine:
    """Single execution gate used by native, GitHub and MCP adapters."""

    @staticmethod
    def mode(spec, job):
        if job.mode not in spec.modes or str(spec.risk) == "CRITICAL":
            raise SafeError("POLICY_DENIED")

    @staticmethod
    async def approval(service, job, name, args, risk, summary, required):
        approved = await service.approved(job, name, args)
        if required and not approved:
            await service.request(job, name, args, risk, summary)
            await service.session.commit()
            from app.tools.registry import ApprovalPending

            raise ApprovalPending()
        return approved
