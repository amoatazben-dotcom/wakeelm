import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from sqlalchemy import select

from app.agent.patches import PatchEngine
from app.bot.handlers.common import say
from app.bot.keyboards import keyboard
from app.core.i18n import tr
from app.db.models.agent import ValidationRun


class AgentInput(StatesGroup):
    task = State()


async def show_job(event, user, agents, ident):
    job = await agents.owned.job(ident)
    buttons = [[("agent.refresh", f"job:status:{job.id}")]]
    if job.status not in {"COMPLETED", "FAILED", "CANCELLED", "LIMIT_REACHED"}:
        buttons.append([("agent.cancel", f"job:cancel:{job.id}")])
    pending = await agents.pending(job.id)
    text = tr(
        user.language,
        "agent.status",
        ident=job.id,
        status=tr(user.language, "agent.state." + job.status),
        mode=job.mode,
        steps=job.current_step,
        limit=job.max_steps,
        calls=job.tool_calls_count,
    )
    if job.failure_code in {
        "SCOPE_REQUIRED",
        "AUTH_REQUIRED",
        "AUTH_FAILED",
    } and job.result_json.get("auth_server_id"):
        buttons.append([("agent.resume_auth", f"job:resume_auth:{job.id}")])
        buttons.append(
            [
                ("mcp.grant", "mc:oauth:" + job.result_json["auth_server_id"]),
                ("common.cancel", "menu:home"),
            ]
        )
    if job.failure_code == "STALE_REPOSITORY":
        from app.integrations.ownership import IntegrationOwnership

        _, repo, _ = await IntegrationOwnership(agents.w.session, user.id).repository_workspace(
            job.workspace_id
        )
        buttons.append([("github.refresh_workspace", "gh:import:" + repo.id)])
    if job.failure_code:
        text += "\n" + tr(user.language, "error." + job.failure_code)
    if job.result_json.get("answer_encrypted"):
        text += "\n" + agents.w.secrets.decrypt(job.result_json["answer_encrypted"])
    verification = job.result_json.get("verification")
    if verification:
        text += "\n" + tr(
            user.language, "agent.verification", tests=verification.get("tests", "NOT_RUN")
        )
    for approval in pending:
        text += (
            "\n"
            + tr(
                user.language,
                "agent.approval_detail",
                tool=approval.tool_name,
                risk=approval.risk_level,
                expires=str(approval.expires_at),
            )
            + "\n"
            + json.dumps(approval.arguments_summary, ensure_ascii=False)
        )
        buttons.append([("agent.approval_details", f"job:details:{approval.id}")])
        if approval.tool_name in {"git.commit", "git.push_branch", "github.create_pull_request"}:
            buttons.append([("agent.diff", f"job:diff:{approval.id}")])
        buttons.append(
            [
                ("agent.approve", f"job:approve:{approval.id}"),
                ("agent.reject", f"job:reject:{approval.id}"),
            ]
        )
    if job.result_json.get("output_encrypted"):
        text += "\n" + agents.w.secrets.decrypt(job.result_json["output_encrypted"])
    if job.result_json.get("workspace_id"):
        buttons.append([("github.open_workspace", f"ws:view:{job.result_json['workspace_id']}")])
    if job.result_json.get("server_id"):
        buttons.append([("mcp.servers", f"mc:server:{job.result_json['server_id']}")])
    if job.kind != "AGENT":
        buttons.append([("common.back", "menu:home")])
    else:
        buttons.append([("common.back", f"ws:view:{job.workspace_id}")])
    await say(event, text[:4000], keyboard(user.language, buttons))


async def changes(event, user, agents, workspace_id):
    rows = await agents.changes(workspace_id)
    buttons = [[("agent.diff", f"change:diff:{row.id}")] for row in rows]
    for row in rows:
        job = await agents.owned.job(row.job_id)
        if row.status == "PROPOSED" and job.status == "COMPLETED" and job.mode == "SUGGEST":
            buttons.append([("agent.apply", f"change:apply:{row.id}")])
        if row.status == "APPLIED":
            buttons.append([("agent.restore", f"change:restore:{row.id}")])
    buttons.append([("common.back", f"ws:view:{workspace_id}")])
    text = (
        tr(user.language, "agent.changes")
        + "\n"
        + "\n".join(f"{row.id} — {row.status} — {len(row.summary_json['files'])}" for row in rows)
    )
    await say(event, text, keyboard(user.language, buttons))


async def tests(event, user, agents, workspace_id):
    await agents.w.owned(workspace_id)
    rows = list(
        await agents.w.session.scalars(
            select(ValidationRun)
            .where(ValidationRun.workspace_id == workspace_id)
            .order_by(ValidationRun.created_at.desc())
            .limit(10)
        )
    )
    text = (
        tr(user.language, "agent.tests")
        + "\n"
        + "\n".join(f"{row.command_id}: {row.status} ({row.exit_code})" for row in rows)
    )
    await say(event, text, keyboard(user.language, [[("common.back", f"ws:view:{workspace_id}")]]))


async def callback(event, user, agents, state: FSMContext):
    prefix, action, ident = event.data.split(":", 2)
    if prefix == "agent":
        await agents.w.owned(ident)
        if action == "start":
            await state.clear()
            await state.update_data(agent_workspace=ident)
            await say(
                event,
                tr(user.language, "agent.choose_mode"),
                keyboard(
                    user.language,
                    [
                        [("agent.read_only", f"mode:READ_ONLY:{ident}")],
                        [("agent.suggest", f"mode:SUGGEST:{ident}")],
                        [("agent.workspace", f"mode:WORKSPACE:{ident}")],
                        [("agent.jobs", f"agent:jobs:{ident}")],
                        [("common.back", f"ws:view:{ident}")],
                    ],
                ),
            )
        elif action == "jobs":
            rows = await agents.jobs(ident)
            await say(
                event,
                tr(user.language, "agent.jobs"),
                keyboard(
                    user.language,
                    [[("agent.state." + row.status, f"job:status:{row.id}")] for row in rows]
                    + [[("common.back", f"ws:view:{ident}")]],
                ),
            )
        elif action == "changes":
            await changes(event, user, agents, ident)
        elif action == "tests":
            await tests(event, user, agents, ident)
    elif prefix == "mode":
        await agents.w.owned(ident)
        from app.agent.schemas import AgentMode
        from app.core.exceptions import SafeError

        if action not in AgentMode.__members__:
            raise SafeError("INVALID_INPUT")
        await state.set_state(AgentInput.task)
        await state.update_data(agent_workspace=ident, agent_mode=action)
        await say(
            event,
            tr(user.language, "agent.task_prompt"),
            keyboard(user.language, [[("common.back", f"ws:view:{ident}")]]),
        )
    elif prefix == "job":
        if action == "resume_auth":
            await agents.resume_after_auth(ident)
            await show_job(event, user, agents, ident)
            return
        if action == "diff":
            from app.github.repositories import RepositoryService
            from app.integrations.sanitizer import ExternalToolOutputSanitizer

            approval = await agents.owned.approval(ident)
            job = await agents.owned.job(approval.job_id)
            link, _, _, git = await RepositoryService(agents.w).context(job.workspace_id)
            diff = ExternalToolOutputSanitizer(agents.w.settings.git_max_output_bytes).clean(
                await git.diff(link.base_commit_sha)
            )
            await event.message.answer_document(
                BufferedInputFile(diff.encode(), "repository-changes.diff")
            )
            return
        if action == "details":
            approval = await agents.owned.approval(ident)
            await event.message.answer_document(
                BufferedInputFile(
                    json.dumps(approval.arguments_summary, ensure_ascii=False, indent=2).encode(),
                    "approval-details.json",
                )
            )
            return
        if action == "cancel":
            await agents.cancel(ident)
        elif action in {"approve", "reject"}:
            approval = await agents.approvals.decide(ident, action == "approve")
            ident = approval.job_id
        await show_job(event, user, agents, ident)
    elif prefix == "change":
        value = await agents.owned.change_set(ident)
        job = await agents.owned.job(value.job_id)
        if action == "diff":
            diff = await PatchEngine(agents.w, job).diff(ident)
            await event.message.answer_document(
                BufferedInputFile(diff["diff"].encode(), "changes.diff"),
                caption=tr(user.language, "agent.diff"),
            )
        elif action == "apply":
            await agents.accept_change(ident)
            await show_job(event, user, agents, job.id)
        elif action == "restore":
            # User must see the exact change-set identifier and confirm restoration.
            await say(
                event,
                tr(user.language, "agent.restore_confirm", ident=ident),
                keyboard(
                    user.language,
                    [
                        [("agent.restore", f"change:restore_yes:{ident}")],
                        [("common.back", f"agent:changes:{value.workspace_id}")],
                    ],
                ),
            )
        elif action == "restore_yes":
            await agents.restore(ident)
            await changes(event, user, agents, value.workspace_id)


async def task_message(event, user, agents, state: FSMContext):
    data = await state.get_data()
    job = await agents.create(
        data["agent_workspace"], data["agent_mode"], event.text, event.chat.id
    )
    await state.clear()
    await show_job(event, user, agents, job.id)


def build_router():
    router = Router(name="agent")
    router.callback_query.register(
        callback, F.data.startswith(("agent:", "mode:", "job:", "change:"))
    )
    router.message.register(task_message, AgentInput.task, F.text)
    return router
