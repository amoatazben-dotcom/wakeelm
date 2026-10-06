import asyncio
import json
import time

from sqlalchemy import select

from app.agent.approvals import TERMINAL
from app.agent.ownership import AgentOwnership
from app.agent.planner import AgentPlanner
from app.agent.schemas import AgentPlan
from app.agent.validator import AgentValidator
from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.agent import AgentStep
from app.services.audit_service import audit
from app.tools.registry import ApprovalPending, ToolRegistry, redact


class AgentOrchestrator:
    def __init__(self, workspaces, models, planner=None, runner=None, notify=None):
        self.w, self.models = workspaces, models
        self.planner = planner or AgentPlanner(models, workspaces)
        self.runner, self.notify = runner, notify

    async def run(self, ident):
        job = await AgentOwnership(self.w.session, self.w.user_id).job(ident)
        if job.status in TERMINAL:
            return job
        started = time.monotonic()
        base_elapsed = job.elapsed_ms

        async def cancelled():
            return bool(await self.w.limits.redis.get("agent:cancel:" + job.id))

        registry = ToolRegistry(self.w, job, cancelled, self.runner)

        async def progress():
            if self.notify:
                await self.notify(job)

        try:
            async with self.w.limits.lock(
                "agent:workspace:" + job.workspace_id, self.w.settings.max_task_duration + 60
            ):
                if await cancelled():
                    raise SafeError("JOB_CANCELLED")
                if not job.started_at:
                    job.started_at = now()
                remaining = self.w.settings.max_task_duration - base_elapsed / 1000
                if remaining <= 0:
                    raise SafeError("AGENT_LIMIT")
                async with asyncio.timeout(remaining):
                    if job.plan_encrypted:
                        plan = AgentPlan.model_validate_json(
                            self.w.secrets.decrypt(job.plan_encrypted)
                        )
                    else:
                        job.status = "PLANNING"
                        await self.w.session.commit()
                        await progress()
                        plan = await self._plan(job, registry)
                        job.plan_encrypted = self.w.secrets.encrypt(plan.model_dump_json())
                        job.plan_json = {
                            "tools": [s.tool_name for s in plan.steps],
                            "risk": plan.risk,
                        }
                    job.status = "RUNNING"
                    await self.w.session.commit()
                    await progress()
                    observations = []
                    while job.current_step < len(plan.steps):
                        if await cancelled():
                            raise SafeError("JOB_CANCELLED")
                        if job.current_step >= job.max_steps:
                            raise SafeError("AGENT_LIMIT")
                        request = plan.steps[job.current_step]
                        step = await self.w.session.scalar(
                            select(AgentStep).where(
                                AgentStep.job_id == job.id,
                                AgentStep.step_number == job.current_step,
                            )
                        )
                        if step is None:
                            step = AgentStep(
                                job_id=job.id,
                                step_number=job.current_step,
                                step_type="TOOL",
                                tool_name=request.tool_name,
                                input_json_redacted=redact(request.arguments),
                                status="RUNNING",
                            )
                            self.w.session.add(step)
                        try:
                            result = await registry.execute(request)
                        except ApprovalPending:
                            step.status = "WAITING_APPROVAL"
                            await self.w.session.commit()
                            return job
                        except SafeError as error:
                            step.status = "FAILED"
                            step.output_summary = error.code
                            step.completed_at = now()
                            await self.w.session.commit()
                            raise
                        observations.append(
                            {
                                "tool": request.tool_name,
                                "result": json.dumps(result, ensure_ascii=False)[:24000],
                            }
                        )
                        step.status = "COMPLETED"
                        step.output_summary = "TOOL_COMPLETED"
                        step.completed_at = now()
                        job.current_step += 1
                        effective_tool = (
                            request.arguments.get("tool_name")
                            if request.tool_name == "agent.request_approval"
                            else request.tool_name
                        )
                        if effective_tool == "workspace.propose_patch":
                            job.result_json = {
                                **job.result_json,
                                "last_patch": result["change_set_id"],
                            }
                        await self.w.session.commit()
                        if await cancelled():
                            raise SafeError("JOB_CANCELLED")
                        if effective_tool == "validation.run" and result["status"] != "PASSED":
                            if result["status"] == "CANCELLED":
                                raise SafeError("JOB_CANCELLED")
                            if (
                                job.repair_count >= self.w.settings.max_repair_attempts
                                or job.replan_count >= self.w.settings.max_replans
                            ):
                                raise SafeError("VALIDATION_FAILED")
                            job.repair_count += 1
                            job.replan_count += 1
                            repair = await self._plan(job, registry, [result])
                            plan.steps = plan.steps[: job.current_step] + repair.steps
                            plan.complete = repair.complete
                            plan.answer = repair.answer
                            job.plan_encrypted = self.w.secrets.encrypt(plan.model_dump_json())
                            job.plan_json = {
                                "tools": [s.tool_name for s in plan.steps],
                                "risk": plan.risk,
                            }
                            await self.w.session.commit()
                        if job.current_step == len(plan.steps) and not plan.complete:
                            if job.replan_count >= self.w.settings.max_replans:
                                raise SafeError("AGENT_LIMIT")
                            job.replan_count += 1
                            next_plan = await self._plan(job, registry, observations[-3:])
                            plan.steps.extend(next_plan.steps)
                            plan.complete = next_plan.complete
                            plan.answer = next_plan.answer
                            job.plan_encrypted = self.w.secrets.encrypt(plan.model_dump_json())
                            await self.w.session.commit()
                    job.result_json = {
                        **job.result_json,
                        "answer_encrypted": self.w.secrets.encrypt(plan.answer),
                    }
                    checks = await AgentValidator(self.w, job, self.runner).validate()
                    job.result_json = {**job.result_json, "verification": checks}
                    if not checks["passed"]:
                        raise SafeError("VALIDATION_FAILED")
                    job.status = "COMPLETED"
                    job.completed_at = now()
                    audit(
                        self.w.session,
                        self.w.user_id,
                        "AGENT_JOB_COMPLETED",
                        "agent_job",
                        job.id,
                        status=job.status,
                    )
        except asyncio.CancelledError:
            job.status = "FAILED"
            job.failure_code = "WORKER_INTERRUPTED"
            raise
        except TimeoutError:
            job.status = "LIMIT_REACHED"
            job.failure_code = "AGENT_LIMIT"
        except SafeError as error:
            job.status = (
                "CANCELLED"
                if error.code == "JOB_CANCELLED"
                else ("LIMIT_REACHED" if error.code == "AGENT_LIMIT" else "FAILED")
            )
            job.failure_code = error.code
            job.failure_message_safe = error.code
        except Exception:
            job.status = "FAILED"
            job.failure_code = "INTERNAL"
            job.failure_message_safe = "INTERNAL"
        finally:
            job.elapsed_ms = base_elapsed + int((time.monotonic() - started) * 1000)
            if job.status in TERMINAL and not job.completed_at:
                job.completed_at = now()
            if job.status in {"FAILED", "LIMIT_REACHED", "CANCELLED"}:
                audit(
                    self.w.session,
                    self.w.user_id,
                    "AGENT_JOB_STOPPED",
                    "agent_job",
                    job.id,
                    status=job.status,
                )
            await self.w.session.commit()
            await progress()
        return job

    async def _plan(self, job, registry, observations=None):
        while True:
            try:
                return await self.planner.plan(job, registry, observations)
            except SafeError as error:
                if error.code != "INVALID_PLAN" or job.replan_count >= self.w.settings.max_replans:
                    raise
                job.replan_count += 1
                await self.w.session.commit()
