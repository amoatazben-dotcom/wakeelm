import json

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.agent.schemas import ToolRequest
from app.bot.handlers.common import say
from app.bot.keyboards import back, keyboard
from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.integrations.oauth import OAuthStateService


class IntegrationInput(StatesGroup):
    pat = State()
    installation = State()
    repo_search = State()
    mcp_name = State()
    mcp_url = State()
    mcp_token = State()
    mcp_scopes = State()
    prompt_args = State()
    task = State()
    commit = State()
    pr_title = State()
    pr_body = State()


def buttons(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def label(user, key, data):
    return InlineKeyboardButton(text=tr(user.language, key), callback_data=data)


async def queued(event, user, agents, job):
    from app.bot.handlers.agent import show_job

    await show_job(event, user, agents, job.id)


async def github_menu(event, user):
    await say(
        event,
        tr(user.language, "menu.github"),
        keyboard(
            user.language,
            [
                [("github.connect", "gh:connect:0")],
                [("github.repositories", "gh:repos:0")],
                [("github.connections", "gh:connections:0")],
                [("github.settings", "gh:settings:0")],
                [("common.back", "menu:home")],
            ],
        ),
    )


async def mcp_menu(event, user):
    await say(
        event,
        tr(user.language, "menu.tools"),
        keyboard(
            user.language,
            [
                [("mcp.add", "mc:add:0")],
                [("mcp.servers", "mc:list:0")],
                [("integrations.registry", "mc:registry:0")],
                [("common.back", "menu:home")],
            ],
        ),
    )


async def repositories(event, user, github, page=0, query=""):
    values, total = await github.repositories(page, query)
    rows = [
        [InlineKeyboardButton(text=row.full_name[:60], callback_data="gh:repo:" + row.id)]
        for row in values
    ]
    nav = []
    if page:
        nav.append(label(user, "common.previous", f"gh:repos:{page - 1}"))
    if (page + 1) * 10 < total:
        nav.append(label(user, "common.next", f"gh:repos:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(
        [label(user, "github.search", "gh:search:0"), label(user, "common.back", "menu:github")]
    )
    await say(event, tr(user.language, "github.repositories"), buttons(rows))


async def server_detail(event, user, mcp, ident):
    server = await mcp.owned.server(ident, False)
    tools = await mcp.tools(ident)
    resources = await mcp.resources(ident)
    text = tr(
        user.language,
        "mcp.detail",
        name=server.name,
        status=tr(user.language, "integration.status." + server.status),
        transport=server.transport,
        auth=server.auth_type,
        tools=len(tools),
        resources=len(resources),
        prompts=len(server.capabilities_json.get("prompts", [])),
        updated=str(server.last_discovered_at),
    )
    await say(
        event,
        text,
        keyboard(
            user.language,
            [
                [("mcp.tools", "mc:tools:" + ident), ("mcp.resources", "mc:resources:" + ident)],
                [("mcp.prompts", "mc:prompts:" + ident), ("mcp.permissions", "mc:tools:" + ident)],
                [("mcp.refresh", "mc:refresh:" + ident), ("mcp.oauth", "mc:oauth:" + ident)],
                [("mcp.disable", "mc:disable:" + ident), ("mcp.remove", "mc:remove:" + ident)],
                [("mcp.task", "mc:task:" + ident), ("mcp.token", "mc:token:" + ident)],
                [("common.back", "mc:list:0")],
            ],
        ),
    )


async def callback(event, user, github, mcp, integration_jobs, agents, state: FSMContext):
    prefix, action, ident = event.data.split(":", 2)
    if prefix == "gh":
        if action == "connect":
            await state.clear()
            await say(
                event,
                tr(user.language, "github.choose"),
                keyboard(
                    user.language,
                    [
                        [("github.app", "gh:app:0")],
                        [("github.pat", "gh:pat:0")],
                        [("common.cancel", "menu:github")],
                    ],
                ),
            )
        elif action in {"app", "pat"}:
            await state.set_state(
                IntegrationInput.installation if action == "app" else IntegrationInput.pat
            )
            await say(
                event,
                tr(
                    user.language,
                    "github.installation_prompt" if action == "app" else "github.token_prompt",
                ),
                back(user.language),
            )
        elif action == "connections":
            rows = await github.list()
            await say(
                event,
                tr(user.language, "github.connections"),
                buttons(
                    [
                        [
                            InlineKeyboardButton(
                                text=f"{row.github_login} · {row.connection_type}",
                                callback_data="gh:connection:" + row.id,
                            )
                        ]
                        for row in rows
                    ]
                    + [[label(user, "common.back", "menu:github")]]
                ),
            )
        elif action == "connection":
            value = await github.owned.connection(ident, False)
            await say(
                event,
                f"{value.github_login} · {value.connection_type} · {tr(user.language, 'integration.status.' + value.status)}\n{value.token_hint or ''}",
                keyboard(
                    user.language,
                    [
                        [("github.refresh", "gh:sync:" + ident)],
                        [("github.revoke", "gh:revoke:" + ident)],
                        [("common.back", "gh:connections:0")],
                    ],
                ),
            )
        elif action == "sync":
            await github.owned.connection(ident)
            await queued(
                event,
                user,
                agents,
                await integration_jobs.enqueue(
                    "GITHUB_SYNC", {"connection_id": ident}, chat_id=event.message.chat.id
                ),
            )
        elif action == "revoke":
            await github.owned.connection(ident, False)
            await say(
                event,
                tr(user.language, "integration.confirm"),
                keyboard(
                    user.language,
                    [
                        [("github.revoke", "gh:revoke_yes:" + ident)],
                        [("common.back", "gh:connection:" + ident)],
                    ],
                ),
            )
        elif action == "revoke_yes":
            await github.revoke(ident)
            await github_menu(event, user)
        elif action == "repos":
            await repositories(event, user, github, int(ident))
        elif action == "search":
            await state.set_state(IntegrationInput.repo_search)
            await say(event, tr(user.language, "github.search_prompt"))
        elif action == "repo":
            repo = await github.owned.repository(ident)
            await say(
                event,
                tr(
                    user.language,
                    "github.repo_detail",
                    name=repo.full_name,
                    visibility=repo.visibility,
                    branch=repo.default_branch,
                    permissions=json.dumps(repo.permissions_json),
                ),
                keyboard(
                    user.language,
                    [[("github.import", "gh:import:" + ident)], [("common.back", "gh:repos:0")]],
                ),
            )
        elif action == "import":
            await github.owned.repository(ident)
            await queued(
                event,
                user,
                agents,
                await integration_jobs.enqueue(
                    "REPOSITORY_IMPORT", {"repository_id": ident}, chat_id=event.message.chat.id
                ),
            )
        elif action == "settings":
            await say(
                event,
                tr(
                    user.language,
                    "github.settings_info",
                    write=str(github.settings.github_write_enabled),
                    comments=str(github.settings.github_comments_enabled),
                ),
                back(user.language),
            )
    elif prefix == "mc":
        if action == "add":
            await state.clear()
            await state.set_state(IntegrationInput.mcp_name)
            await say(event, tr(user.language, "mcp.name_prompt"), back(user.language))
        elif action == "registry":
            from app.integrations.registry import IntegrationRegistry

            await say(event, IntegrationRegistry().describe(), back(user.language))
        elif action == "list":
            rows = await mcp.list()
            await say(
                event,
                tr(user.language, "mcp.servers"),
                buttons(
                    [
                        [
                            InlineKeyboardButton(
                                text=f"{row.name[:45]} · {tr(user.language, 'integration.status.' + row.status)}",
                                callback_data="mc:server:" + row.id,
                            )
                        ]
                        for row in rows[:30]
                    ]
                    + [[label(user, "common.back", "menu:tools")]]
                ),
            )
        elif action == "server":
            await server_detail(event, user, mcp, ident)
        elif action == "refresh":
            await mcp.owned.server(ident, False)
            await queued(
                event,
                user,
                agents,
                await integration_jobs.enqueue(
                    "MCP_DISCOVER", {"server_id": ident}, chat_id=event.message.chat.id
                ),
            )
        elif action == "disable":
            await mcp.disable(ident)
            await server_detail(event, user, mcp, ident)
        elif action == "remove":
            await mcp.owned.server(ident, False)
            await say(
                event,
                tr(user.language, "integration.confirm"),
                keyboard(
                    user.language,
                    [
                        [("mcp.remove", "mc:remove_yes:" + ident)],
                        [("common.back", "mc:server:" + ident)],
                    ],
                ),
            )
        elif action == "remove_yes":
            await mcp.remove(ident)
            await mcp_menu(event, user)
        elif action == "tools":
            values = await mcp.tools(ident)
            await say(
                event,
                tr(user.language, "mcp.review_notice"),
                buttons(
                    [
                        [
                            InlineKeyboardButton(
                                text=f"{row.display_name[:40]} · {row.risk_level} · {'✓' if row.is_enabled else '×'}",
                                callback_data="mt:view:" + row.id,
                            )
                        ]
                        for row in values[:50]
                    ]
                    + [[label(user, "common.back", "mc:server:" + ident)]]
                ),
            )
        elif action == "resources":
            values = await mcp.resources(ident)
            # Opaque identifiers keep long URIs out of Telegram callback_data.
            await state.update_data(
                resource_choices={row.id: {"server_id": ident, "uri": row.uri} for row in values}
            )
            await say(
                event,
                tr(user.language, "mcp.resources"),
                buttons(
                    [
                        [
                            InlineKeyboardButton(
                                text=row.name[:60], callback_data="mr:read:" + row.id
                            )
                        ]
                        for row in values[:50]
                    ]
                    + [[label(user, "common.back", "mc:server:" + ident)]]
                ),
            )
        elif action == "prompts":
            server = await mcp.owned.server(ident, False)
            choices = {
                str(i): {
                    "server_id": ident,
                    "name": row["name"],
                    "parameters": row.get("arguments", []),
                }
                for i, row in enumerate(server.capabilities_json.get("prompts", []))
            }
            await state.update_data(prompt_choices=choices)
            await say(
                event,
                tr(user.language, "mcp.prompts"),
                buttons(
                    [
                        [
                            InlineKeyboardButton(
                                text=value["name"][:60], callback_data="mp:get:" + key
                            )
                        ]
                        for key, value in choices.items()
                    ]
                    + [[label(user, "common.back", "mc:server:" + ident)]]
                ),
            )
        elif action == "token":
            await mcp.owned.server(ident, False)
            await state.set_state(IntegrationInput.mcp_token)
            await state.update_data(mcp_server=ident)
            await say(event, tr(user.language, "mcp.token_prompt"), back(user.language))
        elif action == "oauth":
            await mcp.owned.server(ident, False)
            await state.set_state(IntegrationInput.mcp_scopes)
            await state.update_data(mcp_server=ident)
            await say(event, tr(user.language, "mcp.scope_prompt"), back(user.language))
        elif action == "task":
            await mcp.owned.server(ident)
            await state.set_state(IntegrationInput.task)
            await state.update_data(mcp_server=ident)
            await say(event, tr(user.language, "agent.task_prompt"), back(user.language))
    elif prefix == "mt":
        # Disabled tools remain inspectable through an explicitly owned query.
        from sqlalchemy import select

        from app.db.models.integrations import MCPServer, MCPTool

        tool = await mcp.session.scalar(
            select(MCPTool)
            .join(MCPServer)
            .where(MCPTool.id == ident, MCPServer.user_id == user.id, MCPServer.status != "REMOVED")
        )
        if not tool:
            raise SafeError("NOT_FOUND")
        if action in {"enable", "disable"}:
            await mcp.enable(ident, action == "enable")
        await say(
            event,
            json.dumps(
                {
                    "server_id": tool.mcp_server_id,
                    "name": tool.external_name,
                    "description": tool.description,
                    "risk": tool.risk_level,
                    "schema_fingerprint": tool.metadata_json.get("fingerprint"),
                    "input_schema": tool.input_schema_json,
                },
                ensure_ascii=False,
            )[:3500],
            keyboard(
                user.language,
                [
                    [("mcp.enable", "mt:enable:" + ident), ("mcp.disable", "mt:disable:" + ident)],
                    [("common.back", "mc:tools:" + tool.mcp_server_id)],
                ],
            ),
        )
    elif prefix in {"mr", "mp"}:
        data = await state.get_data()
        key = "resource_choices" if prefix == "mr" else "prompt_choices"
        payload = data.get(key, {}).get(ident)
        if not payload:
            raise SafeError("NOT_FOUND")
        await mcp.owned.server(payload["server_id"])
        if prefix == "mp" and payload.get("parameters"):
            await state.update_data(prompt_payload=payload)
            await state.set_state(IntegrationInput.prompt_args)
            await say(
                event,
                tr(user.language, "mcp.prompt_arguments")
                + "\n"
                + json.dumps(payload["parameters"], ensure_ascii=False),
            )
            return
        await queued(
            event,
            user,
            agents,
            await integration_jobs.enqueue(
                "MCP_RESOURCE" if prefix == "mr" else "MCP_PROMPT",
                payload,
                chat_id=event.message.chat.id,
            ),
        )
    elif prefix == "rp":
        from app.github.repositories import RepositoryService

        service = RepositoryService(agents.w, github)
        link, repo, connection, git = await service.context(ident)
        if action == "view":
            await say(
                event,
                tr(user.language, "github.publish_info"),
                keyboard(
                    user.language,
                    [
                        [("github.commit", "rp:commit:" + ident)],
                        [("github.push", "rp:push:" + ident)],
                        [("github.pr", "rp:pr:" + ident)],
                        [("common.back", "ws:view:" + ident)],
                    ],
                ),
            )
            return
        job = await agents.owned.job(link.metadata_json.get("job_id", ""))
        if action == "commit":
            await state.set_state(IntegrationInput.commit)
            await state.update_data(repository_workspace=ident)
            await say(event, tr(user.language, "github.commit_prompt"))
        elif action == "push":
            await agents.enqueue_action(
                job.id,
                ToolRequest(
                    tool_name="git.push_branch",
                    arguments={
                        "branch": link.working_branch,
                        "expected_head": link.metadata_json.get("committed_sha", ""),
                    },
                ),
            )
            await queued(event, user, agents, job)
        elif action == "pr":
            await state.set_state(IntegrationInput.pr_title)
            await state.update_data(repository_workspace=ident)
            await say(event, tr(user.language, "github.pr_title_prompt"))


async def input_message(event, user, github, mcp, integration_jobs, agents, state: FSMContext):
    current = await state.get_state()
    data = await state.get_data()
    text = event.text or ""
    if current == IntegrationInput.pat.state:
        try:
            await event.delete()
        except Exception:
            pass
        if not text.startswith("github_pat_"):
            raise SafeError("INVALID_CREDENTIAL")
        job = await integration_jobs.enqueue(
            "GITHUB_VERIFY_PAT", {"token": text}, chat_id=event.chat.id
        )
        await state.clear()
        await queued(event, user, agents, job)
    elif current == IntegrationInput.installation.state:
        if not text.isdigit() or not 0 < int(text) < 2**63:
            raise SafeError("INVALID_INPUT")
        states = OAuthStateService(github.session, github.secrets, github.settings)
        url = await states.ticket(user.id, "GITHUB", str(int(text)), {"installation_id": int(text)})
        await state.clear()
        await say(
            event,
            tr(user.language, "integration.open"),
            buttons([[InlineKeyboardButton(text=tr(user.language, "github.app"), url=url)]]),
        )
    elif current == IntegrationInput.repo_search.state:
        await state.clear()
        await repositories(event, user, github, 0, text[:200])
    elif current == IntegrationInput.mcp_name.state:
        if not text or len(text) > 100:
            raise SafeError("INVALID_INPUT")
        await state.update_data(mcp_name=text)
        await state.set_state(IntegrationInput.mcp_url)
        await say(event, tr(user.language, "mcp.url_prompt"))
    elif current == IntegrationInput.mcp_url.state:
        server = await mcp.add(data["mcp_name"], text)
        await state.clear()
        await queued(
            event,
            user,
            agents,
            await integration_jobs.enqueue(
                "MCP_DISCOVER", {"server_id": server.id}, chat_id=event.chat.id
            ),
        )
    elif current == IntegrationInput.mcp_token.state:
        try:
            await event.delete()
        except Exception:
            pass
        server = await mcp.configure_token(data["mcp_server"], text)
        await state.clear()
        await queued(
            event,
            user,
            agents,
            await integration_jobs.enqueue(
                "MCP_DISCOVER", {"server_id": server.id}, chat_id=event.chat.id
            ),
        )
    elif current == IntegrationInput.prompt_args.state:
        try:
            args = json.loads(text)
        except ValueError:
            raise SafeError("INVALID_INPUT") from None
        if (
            not isinstance(args, dict)
            or len(text) > 10000
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in args.items())
        ):
            raise SafeError("INVALID_INPUT")
        payload = data["prompt_payload"]
        parameters = payload.pop("parameters", [])
        if set(args) - {p["name"] for p in parameters} or any(
            p.get("required") and p["name"] not in args for p in parameters
        ):
            raise SafeError("INVALID_INPUT")
        await mcp.owned.server(payload["server_id"])
        payload["arguments"] = args
        await state.clear()
        await queued(
            event,
            user,
            agents,
            await integration_jobs.enqueue("MCP_PROMPT", payload, chat_id=event.chat.id),
        )
    elif current == IntegrationInput.mcp_scopes.state:
        scopes = [] if text.strip() == "-" else text.split()
        url = await mcp.oauth.start(data["mcp_server"], scopes)
        await state.clear()
        await say(
            event,
            tr(user.language, "integration.open"),
            buttons([[InlineKeyboardButton(text=tr(user.language, "mcp.oauth"), url=url)]]),
        )
    elif current == IntegrationInput.task.state:
        server = await mcp.owned.server(data["mcp_server"])
        workspace = await integration_jobs.control_workspace()
        job = await agents.create(workspace.id, "WORKSPACE", text, event.chat.id)
        job.result_json = {"mcp_servers": [server.id]}
        await state.clear()
        await queued(event, user, agents, job)
    elif current == IntegrationInput.commit.state:
        from app.github.repositories import RepositoryService

        link, repo, connection, git = await RepositoryService(agents.w, github).context(
            data["repository_workspace"]
        )
        job = await agents.enqueue_action(
            link.metadata_json["job_id"],
            ToolRequest(
                tool_name="git.commit",
                arguments={"message": text, "expected_files": await git.get_changed_files()},
            ),
        )
        await state.clear()
        await queued(event, user, agents, job)
    elif current == IntegrationInput.pr_title.state:
        if not text.strip() or len(text) > 200:
            raise SafeError("INVALID_INPUT")
        await state.update_data(pr_title=text)
        await state.set_state(IntegrationInput.pr_body)
        await say(event, tr(user.language, "github.pr_body_prompt"))
    elif current == IntegrationInput.pr_body.state:
        from app.github.repositories import RepositoryService

        link, _, _, _ = await RepositoryService(agents.w, github).context(
            data["repository_workspace"]
        )
        job = await agents.enqueue_action(
            link.metadata_json["job_id"],
            ToolRequest(
                tool_name="github.create_pull_request",
                arguments={"title": data["pr_title"], "body": text, "draft": True},
            ),
        )
        await state.clear()
        await queued(event, user, agents, job)


def build_router():
    router = Router(name="integrations")
    router.callback_query.register(
        callback, F.data.startswith(("gh:", "mc:", "mt:", "mr:", "mp:", "rp:"))
    )
    router.message.register(input_message, F.text, StateFilter(*IntegrationInput.__all_states__))
    return router
