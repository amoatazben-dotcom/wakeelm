import fnmatch

from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models.projects import ProjectFile, ProjectSymbol


class SearchService:
    def __init__(self, workspaces):
        self.workspaces = workspaces

    def validate(self, query, max_results):
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 500
            or not 1 <= max_results <= 100
        ):
            raise SafeError("INVALID_INPUT")

    async def text(self, workspace_id, query, glob=None, max_results=30):
        self.validate(query, max_results)
        await self.workspaces.owned(workspace_id)
        if glob and (glob.startswith("/") or ".." in glob.split("/")):
            raise SafeError("PATH_DENIED")
        matches = []
        for file in await self.workspaces.files(workspace_id):
            if (
                file.is_ignored
                or file.is_binary
                or (glob and not fnmatch.fnmatchcase(file.relative_path, glob))
            ):
                continue
            raw = await self.workspaces.read(workspace_id, file.relative_path)
            parsed = self.workspaces.parsers.parse(file.relative_path, raw)
            if parsed.text is None:
                continue
            for line, text in enumerate(parsed.text.splitlines(), 1):
                if query.casefold() in text.casefold():
                    matches.append(
                        {"path": file.relative_path, "line": line, "snippet": text[:300]}
                    )
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        workspace = await self.workspaces.owned(workspace_id)
        self.workspaces.event(workspace, "PROJECT_SEARCHED", count=len(matches))
        return matches

    async def files(self, workspace_id, query, max_results=30):
        self.validate(query, max_results)
        return [
            {"path": f.relative_path, "file_id": f.id}
            for f in await self.workspaces.files(workspace_id)
            if query.casefold() in f.relative_path.casefold()
        ][:max_results]

    async def symbols(self, workspace_id, query, max_results=30):
        self.validate(query, max_results)
        await self.workspaces.owned(workspace_id)
        rows = await self.workspaces.session.execute(
            select(ProjectSymbol, ProjectFile.relative_path)
            .join(ProjectFile)
            .where(ProjectFile.workspace_id == workspace_id, ProjectFile.is_ignored.is_(False))
            .order_by(ProjectSymbol.id)
        )
        return [
            {
                "path": path,
                "line": symbol.start_line,
                "end_line": symbol.end_line,
                "name": symbol.qualified_name,
                "type": symbol.symbol_type,
            }
            for symbol, path in rows
            if query.casefold() in symbol.qualified_name.casefold()
        ][:max_results]
