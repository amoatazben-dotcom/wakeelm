import io
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.handlers.common import say
from app.bot.keyboards import back, keyboard
from app.context.engine import ContextEngine
from app.core.exceptions import SafeError
from app.core.i18n import tr
from app.db.models.projects import WorkspaceEvent
from app.services.search_service import SearchService


class ProjectInput(StatesGroup):
    search = State()
    question = State()


async def files_menu(event, user):
    await say(
        event,
        tr(user.language, "menu.files"),
        keyboard(
            user.language,
            [
                [("files.upload", "ws:upload"), ("files.archive", "ws:upload")],
                [("files.list", "ws:list:0")],
                [("common.back", "menu:home")],
            ],
        ),
    )


async def upload_prompt(event, user):
    await say(event, tr(user.language, "files.prompt"), back(user.language))


class BoundedUpload(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise SafeError("UPLOAD_TOO_LARGE")
        return super().write(data)


async def upload(event, user, workspaces, state: FSMContext):
    document = event.document
    if (
        document.file_size is not None
        and document.file_size > workspaces.settings.max_upload_size_mb * 1024**2
    ):
        raise SafeError("UPLOAD_TOO_LARGE")
    stream = BoundedUpload(workspaces.settings.max_upload_size_mb * 1024**2)
    await event.bot.download(document, destination=stream)
    workspace = await workspaces.ingest(
        document.file_name or "upload.bin", stream.getvalue(), document.mime_type
    )
    await state.clear()
    await say(
        event, tr(user.language, "files.saved", name=workspace.name, count=workspace.file_count)
    )
    await workspace_detail(event, user, workspaces, workspace.id)


async def workspace_list(event, user, workspaces, page=0):
    rows, total = await workspaces.list(page)
    buttons = [
        [InlineKeyboardButton(text=row.name[:60], callback_data=f"ws:view:{row.id}")]
        for row in rows
    ]
    nav = []
    if page:
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.previous"), callback_data=f"ws:list:{page - 1}"
            )
        )
    if (page + 1) * 10 < total:
        nav.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.next"), callback_data=f"ws:list:{page + 1}"
            )
        )
    if nav:
        buttons.append(nav)
    buttons.append(
        [InlineKeyboardButton(text=tr(user.language, "common.back"), callback_data="menu:files")]
    )
    await say(
        event,
        tr(user.language, "files.list") if rows else tr(user.language, "common.empty"),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def workspace_detail(event, user, workspaces, ident):
    workspace = await workspaces.owned(ident)
    rows = [
        [("project.scan", f"ws:scan:{ident}"), ("project.info", f"ws:info:{ident}")],
        [("project.ask", f"ws:ask:{ident}"), ("project.search", f"ws:search:{ident}")],
        [("project.browse", f"ws:browse:{ident}")],
        [("project.agent", f"agent:start:{ident}"), ("project.changes", f"agent:changes:{ident}")],
        [("project.tests", f"agent:tests:{ident}"), ("project.events", f"ws:events:{ident}")],
        [("project.delete", f"ws:delete:{ident}")],
        [("common.back", "ws:list:0")],
    ]
    await say(
        event,
        tr(
            user.language,
            "project.detail",
            name=workspace.name,
            count=workspace.file_count,
            size=workspace.size_bytes,
            status=tr(user.language, "status." + workspace.status),
        ),
        keyboard(user.language, rows),
    )


async def browse(event, user, workspaces, state, ident, directory="", page=0):
    items, total = await workspaces.browse(ident, directory, page)
    # Short-lived per-user opaque navigation handles keep Telegram callback data under 64 bytes.
    data = await state.get_data()
    navigation = data.get("navigation", {})
    buttons = []

    def nav(path, next_page):
        key = uuid.uuid4().hex[:12]
        navigation[key] = {"workspace": ident, "path": path, "page": next_page}
        return "nav:" + key

    for item in items:
        if item["kind"] == "directory":
            callback = nav(item["path"], 0)
            label = "📁 " + item["path"].rsplit("/", 1)[-1]
        else:
            callback = f"file:view:{item['id']}"
            label = "📄 " + item["path"].rsplit("/", 1)[-1]
        buttons.append([InlineKeyboardButton(text=label[:65], callback_data=callback)])
    pages = []
    if page:
        pages.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.previous"), callback_data=nav(directory, page - 1)
            )
        )
    if (page + 1) * 10 < total:
        pages.append(
            InlineKeyboardButton(
                text=tr(user.language, "common.next"), callback_data=nav(directory, page + 1)
            )
        )
    if pages:
        buttons.append(pages)
    if directory:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=tr(user.language, "files.parent"),
                    callback_data=nav(directory.rsplit("/", 1)[0] if "/" in directory else "", 0),
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text=tr(user.language, "files.root"), callback_data=nav("", 0)),
            InlineKeyboardButton(
                text=tr(user.language, "common.back"), callback_data=f"ws:view:{ident}"
            ),
        ]
    )
    await state.update_data(navigation=dict(list(navigation.items())[-100:]))
    await say(
        event,
        tr(user.language, "project.browser", path=directory or "/", page=page + 1, total=total),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def actions(event, user, workspaces, state: FSMContext):
    parts = event.data.split(":")
    action = parts[1]
    if action == "upload":
        await upload_prompt(event, user)
        return
    if action == "list":
        await workspace_list(event, user, workspaces, int(parts[2]))
        return
    ident = parts[2]
    workspace = await workspaces.owned(ident)
    if action == "view":
        await workspace_detail(event, user, workspaces, ident)
    elif action == "browse":
        await browse(event, user, workspaces, state, ident)
    elif action == "scan":
        await workspaces.index(ident)
        await say(event, tr(user.language, "project.indexed"))
        await workspace_detail(event, user, workspaces, ident)
    elif action == "info":
        manifest = await workspaces.manifest(ident)
        text = tr(
            user.language,
            "project.manifest",
            languages=", ".join(manifest["languages"]),
            frameworks=", ".join(manifest["frameworks"]),
            builds=", ".join(manifest["build_systems"]),
            tests=", ".join(manifest["test_frameworks"]),
        )
        await say(event, text, keyboard(user.language, [[("common.back", f"ws:view:{ident}")]]))
    elif action in {"search", "ask"}:
        await state.set_state(ProjectInput.search if action == "search" else ProjectInput.question)
        await state.update_data(workspace_id=ident)
        await say(
            event,
            tr(
                user.language,
                "project.search_prompt" if action == "search" else "project.question_prompt",
            ),
            keyboard(user.language, [[("common.cancel", "cancel")]]),
        )
    elif action == "delete":
        await state.update_data(delete_workspace=ident)
        await say(
            event,
            tr(user.language, "project.delete_confirm"),
            keyboard(
                user.language,
                [[("common.confirm", f"ws:confirmed:{ident}")], [("common.cancel", "cancel")]],
            ),
        )
    elif action == "confirmed":
        if (await state.get_data()).get("delete_workspace") != ident:
            raise SafeError("INVALID_INPUT")
        await workspaces.delete(ident)
        await state.clear()
        await workspace_list(event, user, workspaces)
    elif action == "events":
        events = await workspaces.session.scalars(
            select(WorkspaceEvent)
            .where(WorkspaceEvent.workspace_id == workspace.id, WorkspaceEvent.user_id == user.id)
            .order_by(WorkspaceEvent.id.desc())
            .limit(20)
        )
        await say(
            event,
            "\n".join(tr(user.language, "audit." + row.action) for row in events)
            or tr(user.language, "common.empty"),
            keyboard(user.language, [[("common.back", f"ws:view:{ident}")]]),
        )


async def navigation(event, user, workspaces, state: FSMContext):
    data = (await state.get_data()).get("navigation", {}).get(event.data.split(":")[1])
    if not data:
        raise SafeError("NOT_FOUND")
    await browse(event, user, workspaces, state, data["workspace"], data["path"], data["page"])


async def file_actions(event, user, workspaces, state: FSMContext):
    _, action, ident = event.data.split(":")
    file = await workspaces.file(int(ident))
    markup = keyboard(
        user.language,
        [
            [("files.view", f"file:read:{file.id}"), ("files.info", f"file:info:{file.id}")],
            [("files.search", f"file:search:{file.id}")],
            [("common.back", f"ws:browse:{file.workspace_id}")],
        ],
    )
    if action == "read":
        if file.is_binary:
            raise SafeError("BINARY_FILE")
        parsed = workspaces.parsers.parse(
            file.relative_path, await workspaces.read(file.workspace_id, file.relative_path)
        )
        if parsed.text is None:
            raise SafeError("BINARY_FILE")
        if len(parsed.text) > 3500:
            await event.message.answer_document(
                BufferedInputFile(parsed.text.encode(), filename=file.file_name + ".txt")
            )
        else:
            await say(event, parsed.text or tr(user.language, "common.empty"), markup)
    elif action == "info":
        await say(
            event,
            tr(
                user.language,
                "files.info_detail",
                path=file.relative_path,
                size=file.size_bytes,
                language=file.language or "—",
                sha=file.sha256,
            ),
            markup,
        )
    elif action == "search":
        await state.set_state(ProjectInput.search)
        await state.update_data(workspace_id=file.workspace_id, search_glob=file.relative_path)
        await say(
            event,
            tr(user.language, "project.search_prompt"),
            keyboard(user.language, [[("common.cancel", "cancel")]]),
        )
    else:
        await say(event, file.relative_path, markup)


async def search_input(event, user, workspaces, state: FSMContext):
    data = await state.get_data()
    results = await SearchService(workspaces).text(
        data["workspace_id"], event.text, glob=data.get("search_glob"), max_results=15
    )
    await state.clear()
    await say(
        event,
        "\n".join(f"{row['path']}:{row['line']} | {row['snippet'][:100]}" for row in results)
        or tr(user.language, "common.empty"),
        keyboard(user.language, [[("common.back", f"ws:view:{data['workspace_id']}")]]),
    )


async def question_input(event, user, workspaces, models, state: FSMContext):
    data = await state.get_data()
    result = await ContextEngine(workspaces).answer(data["workspace_id"], event.text, models)
    await state.clear()
    text = result["answer"] + "\n" + "\n".join(result["citations"])
    for begin in range(0, len(text), 3500):
        await say(event, text[begin : begin + 3500])
    await workspace_detail(event, user, workspaces, data["workspace_id"])


def build_router():
    router = Router()
    router.message.register(upload, F.document)
    router.callback_query.register(actions, F.data.startswith("ws:"))
    router.callback_query.register(navigation, F.data.startswith("nav:"))
    router.callback_query.register(file_actions, F.data.startswith("file:"))
    router.message.register(search_input, ProjectInput.search, F.text)
    router.message.register(question_input, ProjectInput.question, F.text)
    return router
